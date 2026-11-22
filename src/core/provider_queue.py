"""Durable admission for model requests shared by the web and executor processes."""
import asyncio
from contextlib import closing, contextmanager
from email.utils import parsedate_to_datetime
import hashlib
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit

from src import config
from src.workflow.executor_lease import ExecutorLeaseUnavailable, ExecutorProcessLease
from src.workflow.executor_process import process_is_alive

log = logging.getLogger(__name__)
FIRST_WORD_SECONDS = 120
IDLE_SECONDS = 600
POLL_SECONDS = 0.5


class GroupPaused(RuntimeError):
    def __init__(self, reason):
        super().__init__("供应商分组已暂停：" + reason)


class ProbeBusy(RuntimeError):
    """A probe reports the existing request without adding a second one."""


def cooldown_seconds(error, now):
    """Take the longest explicit instruction. No duration means manual review."""
    message = str(error)
    if re.search(r"联系客服|解除限制|contact.{0,20}support", message, re.I):
        return None
    headers = getattr(getattr(error, "response", None), "headers", {})
    delays = []
    header = headers.get("retry-after")
    if header:
        try:
            delays.append(float(header))
        except ValueError:
            try:
                delays.append(parsedate_to_datetime(header).timestamp() - now)
            except (ValueError, TypeError, OverflowError):
                pass
    for value, unit in re.findall(
        r"(?:请在|等待|retry\s+(?:in|after)|try again in)\s*(\d+(?:\.\d+)?)\s*(秒|分钟|seconds?|s\b|minutes?)",
        message, re.I,
    ):
        delays.append(float(value) * (60 if unit.lower().startswith(("分", "min")) else 1))
    finite = [d for d in delays if math.isfinite(d)]
    return max(1, math.ceil(max(finite))) if finite else None


class ProviderQueue:
    def __init__(self, path: Path):
        self.path = path
        self.lock = path.with_suffix(".lock")
        self.local_requests = 0
        self.probe_only_if_idle = False

    @classmethod
    def for_provider(cls, provider):
        # Model names, API dialects and duplicate provider entries can share a key.
        alias = str(provider.get("request_group") or "").strip()
        account = ("group\0" + alias if alias else "account\0" +
                   urlsplit(provider["base_url"]).netloc.lower() + "\0" + provider["api_key"])
        group = hashlib.sha256(account.encode()).hexdigest()
        return cls(config.DATA_DIR / "system" / "provider-queues" / (group + ".sqlite"))

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=8)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS gate (
                id INTEGER PRIMARY KEY, state TEXT, reason TEXT, until REAL,
                started REAL, first_word REAL, last_word REAL, model TEXT)""")
            db.execute("INSERT OR IGNORE INTO gate VALUES (1,'ready','',0,0,0,0,'')")
            db.execute("CREATE TABLE IF NOT EXISTS waiting (id INTEGER PRIMARY KEY AUTOINCREMENT, pid INTEGER)")
            yield db

    def _state(self, db):
        row = db.execute("SELECT * FROM gate").fetchone()
        if row["state"] == "active":
            # The OS releases this lock on process death. Never replay an orphan.
            lease = ExecutorProcessLease(self.lock)
            try:
                lease.acquire(0)
            except ExecutorLeaseUnavailable:
                return row
            try:
                db.execute("UPDATE gate SET state='paused',reason='上次请求中断，结果未确认'")
            finally:
                lease.release()
        elif row["state"] == "cooldown" and row["until"] <= time.time():
            db.execute("UPDATE gate SET state='ready',reason='',until=0")
        return db.execute("SELECT * FROM gate").fetchone()

    def status(self):
        with self.transaction() as db:
            row = dict(self._state(db))
            self._prune_waiters(db)
            row["waiting"] = db.execute("SELECT COUNT(*) FROM waiting").fetchone()[0]
            row["first_word_overdue"] = (row["state"] == "active" and not row["first_word"]
                                         and time.time() - row["started"] >= FIRST_WORD_SECONDS)
            return row

    def resume(self):
        with self.transaction() as db:
            if self._state(db)["state"] != "paused":
                raise ValueError("只有已暂停的分组可以手动恢复")
            with ExecutorProcessLease(self.lock) as lease:
                try:
                    lease.acquire(0)
                except ExecutorLeaseUnavailable as exc:
                    raise ValueError("上一次请求仍在关闭，请稍后恢复") from exc
                db.execute("UPDATE gate SET state='ready',reason='',until=0")

    @staticmethod
    def _prune_waiters(db):
        for (pid,) in db.execute("SELECT DISTINCT pid FROM waiting").fetchall():
            if not process_is_alive(pid):
                db.execute("DELETE FROM waiting WHERE pid=?", (pid,))

    def finish(self, state, reason="", until=0):
        with self.transaction() as db:
            db.execute("UPDATE gate SET state=?, reason=?, until=?", (state, reason, until))

    def progress(self, first_word, last_word):
        with self.transaction() as db:
            db.execute("UPDATE gate SET first_word=?, last_word=?", (first_word, last_word))

    async def acquire(self, model):
        with self.transaction() as db:
            state = self._state(db)
            if state["state"] == "paused":
                raise GroupPaused(state["reason"])
            if self.probe_only_if_idle:
                self._prune_waiters(db)
                if state["state"] == "cooldown":
                    raise ProbeBusy(f"分组冷却中，剩余 {math.ceil(state['until'] - time.time())} 秒")
                if state["state"] == "active":
                    elapsed = int(time.time() - state["started"])
                    raise ProbeBusy(f"{state['model']} 已运行 {elapsed} 秒，本次未另发测试请求")
                if db.execute("SELECT 1 FROM waiting LIMIT 1").fetchone():
                    raise ProbeBusy("分组有任务排队，本次未另发测试请求")
            ticket = db.execute("INSERT INTO waiting(pid) VALUES (?)", (os.getpid(),)).lastrowid
        try:
            while True:
                with self.transaction() as db:
                    state = self._state(db)
                    for row in db.execute("SELECT id,pid FROM waiting ORDER BY id"):
                        if row["id"] == ticket:
                            if state["state"] == "ready":
                                lease = ExecutorProcessLease(self.lock)
                                try:
                                    lease.acquire(0)
                                except ExecutorLeaseUnavailable:
                                    break  # The preceding response is still closing.
                                try:
                                    db.execute("DELETE FROM waiting WHERE id=?", (ticket,))
                                    db.execute("""UPDATE gate SET state='active',reason='',until=0,
                                        started=?, first_word=0,last_word=0,model=?""", (time.time(), model))
                                    db.commit()
                                except BaseException:
                                    lease.release()
                                    raise
                                return lease
                            break
                        if process_is_alive(row["pid"]):
                            break
                        db.execute("DELETE FROM waiting WHERE id=?", (row["id"],))
                await asyncio.sleep(POLL_SECONDS)
        finally:
            with self.transaction() as db:
                db.execute("DELETE FROM waiting WHERE id=?", (ticket,))


def has_body(chunk):
    content = getattr(getattr(chunk, "message", None), "content", None)
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and any(
        (isinstance(block, str) and block.strip()) or
        (isinstance(block, dict) and block.get("type") in ("text", "output_text")
         and isinstance(block.get("text"), str) and block["text"].strip())
        for block in content)


async def guarded_stream(queue, model, make_stream, *, retry_after_cooldown=True):
    """Keep the lease through stream cleanup. Heartbeats/thinking never reset idle time."""
    from contextlib import aclosing
    queue.local_requests += 1
    try:
        async with aclosing(_dispatch(queue, model, make_stream, retry_after_cooldown)) as stream:
            async for item in stream:
                yield item
    finally:
        queue.local_requests -= 1


async def _dispatch(queue, model, make_stream, retry_after_cooldown):
    while True:
        lease = await queue.acquire(model)
        loop = asyncio.get_running_loop()
        started = last = loop.time()
        first_word = 0
        saved_at = 0
        warned = False
        stream = pending = None
        try:
            stream = make_stream()
            while True:
                pending = asyncio.ensure_future(anext(stream))
                while True:
                    now = loop.time()
                    if not first_word and not warned and now >= started + FIRST_WORD_SECONDS:
                        warned = True
                        log.warning("%s 等待首字超过两分钟，继续等待原请求", model)
                    if now >= last + IDLE_SECONDS:
                        raise GroupPaused("连续十分钟无正文，结果未确认，请手动恢复分组")
                    deadline = last + IDLE_SECONDS
                    if not first_word and not warned:
                        deadline = min(deadline, started + FIRST_WORD_SECONDS)
                    done, _ = await asyncio.wait((pending,), timeout=max(0, deadline - now))
                    if done:
                        break
                chunk = pending.result()
                pending = None
                if has_body(chunk):
                    last = loop.time()
                    stamp = time.time()
                    if not first_word or last - saved_at >= 2:
                        first_word = first_word or stamp
                        queue.progress(first_word, stamp)
                        saved_at = last
                yield chunk
        except StopAsyncIteration:
            queue.finish("ready")
            return
        except BaseException as exc:
            status = getattr(exc, "status_code", None)
            if status == 429:
                delay = cooldown_seconds(exc, time.time())
                if delay is None or first_word:
                    reason = "供应商限流，请确认解除限制后手动恢复" if not first_word else "部分正文已返回，结果未确认"
                    queue.finish("paused", reason)
                    raise GroupPaused(reason) from exc
                queue.finish("cooldown", "供应商要求冷却", time.time() + delay)
                if not retry_after_cooldown:
                    raise
            elif isinstance(status, int) and 400 <= status < 600 and not first_word:
                queue.finish("ready")
                raise
            else:
                reason = (str(exc).removeprefix("供应商分组已暂停：") if isinstance(exc, GroupPaused)
                          else "请求中断，结果未确认，请手动恢复分组")
                queue.finish("paused", reason)
                if isinstance(exc, Exception) and not isinstance(exc, GroupPaused):
                    raise GroupPaused(reason) from exc
                raise
        finally:
            try:
                if pending is not None and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                if stream is not None:
                    await stream.aclose()
            finally:
                lease.release()
