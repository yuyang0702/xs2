"""Only local streams, subprocesses and HTTPX mock transports; no provider credentials."""
import asyncio
from contextlib import aclosing
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest

from src.core import provider_queue as pq
from src.core.provider_queue import GroupPaused, ProviderQueue, guarded_stream


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(pq, "POLL_SECONDS", .01)
    return ProviderQueue(tmp_path / "queue.sqlite")


def word(text):
    return SimpleNamespace(message=SimpleNamespace(content=text))


def test_fifteen_jobs_are_fifo_and_an_independent_group_can_progress(queue):
    order = []
    release = asyncio.Event()
    async def run():
        async def piece(idx):
            order.append(idx)
            if idx == 0:
                await release.wait()
            yield word(str(idx))
        tasks = [asyncio.create_task(collect(guarded_stream(
            ProviderQueue(queue.path), str(i), lambda idx=i: piece(idx)))) for i in range(15)]
        async with asyncio.timeout(3):
            while queue.status()["waiting"] != 14:
                await asyncio.sleep(.005)
        assert order == [0]
        await collect(guarded_stream(ProviderQueue(queue.path.with_name("other.sqlite")),
                                     "independent", lambda: piece(99)))
        release.set()
        await asyncio.gather(*tasks)
    asyncio.run(run())
    assert order == [0, 99, *range(1, 15)]


async def collect(stream):
    async with aclosing(stream):
        return [chunk async for chunk in stream]


def test_warning_and_idle_cover_first_response_and_ignore_reasoning(queue, monkeypatch, caplog):
    monkeypatch.setattr(pq, "FIRST_WORD_SECONDS", .06)
    monkeypatch.setattr(pq, "IDLE_SECONDS", .24)
    calls = 0

    async def thinking():
        nonlocal calls
        calls += 1
        while True:
            await asyncio.sleep(.015)
            yield word([{"type": "reasoning", "text": "still thinking"}])

    async def run():
        once = asyncio.create_task(collect(guarded_stream(queue, "writer", thinking)))
        await asyncio.sleep(.12)
        assert queue.status()["first_word_overdue"]
        assert calls == 1 and not once.done()
        with pytest.raises(GroupPaused):
            await once
        assert queue.status()["state"] == "paused"
        with pytest.raises(GroupPaused):
            await collect(guarded_stream(ProviderQueue(queue.path), "probe", thinking))
        assert calls == 1
        assert caplog.text.count("继续等待原请求") == 1
    asyncio.run(run())


def test_progress_refreshes_idle_then_midstream_stall_requires_manual_resume(queue, monkeypatch):
    monkeypatch.setattr(pq, "IDLE_SECONDS", .15)
    received = []
    async def stream():
        for _ in range(6):
            await asyncio.sleep(.04)
            yield word("正文")
        await asyncio.sleep(2)
    async def run():
        with pytest.raises(GroupPaused):
            async for chunk in guarded_stream(queue, "revision", stream):
                received.append(chunk)
        assert len(received) == 6
        assert queue.status()["first_word"]
        queue.resume()
        assert queue.status()["state"] == "ready"
    asyncio.run(run())


class Limited(Exception):
    status_code = 429
    response = SimpleNamespace(headers={"retry-after": "1"})


def test_cooldown_survives_reopen_and_blocks_other_clients(queue):
    async def limited():
        raise Limited("请在 1 秒后重试")
        yield

    async def run():
        with pytest.raises(Limited):
            await collect(guarded_stream(queue, "probe", limited, retry_after_cooldown=False))
        reopened = ProviderQueue(queue.path)
        until = reopened.status()["until"]
        assert until > time.time()
        with pytest.raises(ValueError):
            reopened.resume()
        async def write():
            assert time.time() >= until
            yield word("ok")
        await collect(guarded_stream(reopened, "new", write))
        assert reopened.status()["state"] == "ready"
        assert pq.cooldown_seconds(Limited("请在 539 秒后重试"), time.time()) == 539
        assert pq.cooldown_seconds(Limited("请联系客服解除限制"), time.time()) is None
    asyncio.run(run())


def test_manual_grouping_and_sync_entry_points(queue):
    from src.core.queued_model import install_queue
    base = {"api_key": "mock-a", "base_url": "https://mock.invalid/v1"}
    group = {**base, "request_group": "shared"}
    assert ProviderQueue.for_provider(group).path == ProviderQueue.for_provider(
        {**group, "api_key": "mock-b"}).path
    assert ProviderQueue.for_provider(base).path != ProviderQueue.for_provider(
        {**base, "api_key": "mock-b"}).path
    def chunks():
        assert queue.status()["state"] == "active"
        yield word("OK")
    def single():
        assert queue.status()["state"] == "active"
        return 123
    model = SimpleNamespace(_stream=chunks, _generate=single, _astream=None, _agenerate=None)
    install_queue(model, queue, "sync", retry_after_cooldown=False)
    assert [chunk.message.content for chunk in model._stream()] == ["OK"]
    assert model._generate() == 123
    assert queue.status()["state"] == "ready"


def test_support_hold_is_not_retried_or_skipped(queue):
    from src.core.provider_errors import present_session_error
    from src.workflow.failure_policy import can_auto_retry, should_auto_skip
    async def blocked():
        raise Limited("请联系客服解除限制")
        yield
    with pytest.raises(GroupPaused) as failure:
        asyncio.run(collect(guarded_stream(queue, "writer", blocked)))
    assert queue.status()["state"] == "paused"
    safe = present_session_error(failure.value)
    state = SimpleNamespace(status="failed", error=safe.message, automatic_retry_count=0)
    node = SimpleNamespace(auto_retry_count=3, fail_auto_skip=True)
    assert not can_auto_retry(node, state) and not should_auto_skip(node, state)


def test_crashed_executor_cannot_resend_and_waiter_cannot_steal_live_lease(queue):
    child = """
import asyncio,sys
from pathlib import Path
from src.core.provider_queue import ProviderQueue
async def main():
    lease = await ProviderQueue(Path(sys.argv[1])).acquire("child")
    print("sent",flush=True)
    await asyncio.sleep(60)
asyncio.run(main())
"""
    process = subprocess.Popen([sys.executable, "-c", child, str(queue.path)], stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == b"sent"
        async def run():
            waiting = asyncio.create_task(queue.acquire("other"))
            await asyncio.sleep(.1)
            assert not waiting.done()
            process.kill()
            process.wait(timeout=10)
            assert queue.status()["state"] == "paused"
            assert not waiting.done()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        asyncio.run(run())
        assert ProviderQueue(queue.path).status()["state"] == "paused"
    finally:
        process.kill()
        process.wait(timeout=10)


def test_real_factory_bound_writer_revision_and_probe_share_one_queue(tmp_path, monkeypatch):
    from src import config
    from src.core import model_manager, model_probe
    from src.core.llm_client import create_llm
    from langchain_core.messages import HumanMessage

    cfg = tmp_path / "models.json"
    provider = {"provider_type": "openai_compatible", "base_url": "https://local.invalid/v1",
                "api_key": "offline-test", "models": ["new", "edit", "probe"]}
    cfg.write_text(json.dumps({"providers": {"one": provider, "alias": provider}}))
    manager = model_manager.ModelManager(str(cfg))
    monkeypatch.setattr(model_manager, "get_model_manager", lambda: manager)
    monkeypatch.setattr(model_probe, "get_model_manager", lambda: manager)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pq, "POLL_SECONDS", .01)
    active = maximum = 0
    sent = []
    async def mock_http(request):
        nonlocal active, maximum
        name = json.loads(request.content)["model"]
        active += 1
        maximum = max(maximum, active)
        sent.append(name)
        data = {"id": name, "model": name, "object": "chat.completion.chunk", "created": 0,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]}
        class ResponseStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                nonlocal active
                yield ("data: " + json.dumps(data) + "\n\n").encode()
                await asyncio.sleep(.075)
                active -= 1
                yield b"data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ResponseStream())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock_http)) as client:
            def factory(**kwargs):
                return create_llm(http_async_client=client, **kwargs)
            monkeypatch.setattr(model_probe, "create_llm", factory)
            writer = factory(model_override="one:new").bind_tools([])
            editor = factory(model_override="alias:edit")
            draft_task = asyncio.create_task(writer.ainvoke([HumanMessage(content="新写")]))
            async with asyncio.timeout(5):
                while not sent:
                    await asyncio.sleep(.001)
            with pytest.raises(model_probe.ModelProbeError, match="未另发测试请求"):
                await model_probe.probe_configured_model("alias:probe")
            draft, edit = await asyncio.gather(draft_task, editor.ainvoke("返修"))
            probe = await model_probe.probe_configured_model("alias:probe")
            assert draft.content == edit.content == probe["content"] == "OK"
    asyncio.run(run())
    assert maximum == 1 and sorted(sent) == ["edit", "new", "probe"]


def test_anthropic_adapter_waits_for_an_openai_compatible_alias(tmp_path, monkeypatch):
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk
    from src import config
    from src.core import model_manager
    from src.core.llm_client import create_llm
    cfg = tmp_path / "models.json"
    common = {"base_url": "https://fake.invalid", "api_key": "offline", "models": ["model-a"]}
    cfg.write_text(json.dumps({"providers": {
        "claude": {**common, "provider_type": "anthropic"},
        "other": {**common, "provider_type": "openai_compatible"},
    }}))
    manager = model_manager.ModelManager(str(cfg))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(model_manager, "get_model_manager", lambda: manager)
    monkeypatch.setattr(pq, "POLL_SECONDS", .01)
    sent = []
    async def fake_stream(self, *args, **kwargs):
        sent.append(True)
        yield ChatGenerationChunk(message=AIMessageChunk(content="OK"))
    monkeypatch.setattr(ChatAnthropic, "_astream", fake_stream)
    async def run():
        first = create_llm(model_override="other:model-a").provider_queue
        lease = await first.acquire("other:model-a")
        try:
            model = create_llm(model_override="claude:model-a")
            task = asyncio.create_task(model.ainvoke("检查"))
            async with asyncio.timeout(3):
                while not first.status()["waiting"]:
                    await asyncio.sleep(.01)
            assert not sent
            first.finish("ready")
        finally:
            lease.release()
        assert (await asyncio.wait_for(task, 3)).content == "OK"
    asyncio.run(run())
