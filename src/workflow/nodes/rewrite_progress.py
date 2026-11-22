"""Resume a paragraph rewrite node against its frozen editor input."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
import json
import logging
import re
import sqlite3

from .base import NodeResult
from ..model_preferences import atomic_write
from ..variable_resolution import resolve_placeholders, resolve_workspace_file_path

logger = logging.getLogger(__name__)


def _words(text):
    return "".join(char for char in text if char.isalnum())


class RewriteProgress:
    def __init__(self, path, view, identity):
        self.path = path
        self.view = view
        self.report = view["zhuque_review"]
        self.units = {u["id"]: u for u in self.report["rewrite_units"]}
        self.paragraphs = {p["id"]: p["text"] for p in view["source_body"]["paragraphs"]}
        self.references = {**self.report.get("reference_excerpts", {}),
                           **{k: self.paragraphs[k] for k in self.report["reference_paragraphs"]}}
        binding = json.dumps([view, identity], sort_keys=True, ensure_ascii=False).encode()
        self.key = hashlib.sha256(binding).hexdigest()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS edits (binding TEXT, id TEXT, data TEXT, PRIMARY KEY(binding,id))")
            db.execute("CREATE TABLE IF NOT EXISTS rejections (binding TEXT, id TEXT, PRIMARY KEY(binding,id))")

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {k: json.loads(v) for k, v in db.execute("SELECT id,data FROM edits WHERE binding=?", (self.key,))}

    def invalidate(self, row):
        with closing(sqlite3.connect(self.path, timeout=20)) as db, db:
            db.execute("DELETE FROM edits WHERE binding=? AND id=? AND data=?",
                       (self.key, row["id"], json.dumps(row, ensure_ascii=False)))

    def store(self, row):
        unit = self.units[row["id"]]
        text = row["replacement"]
        if (row["reference_id"] not in self.references or not isinstance(text, str)
                or not _words(text) or _words(text) == _words(unit["old"])):
            raise ValueError(f'{unit["id"]} 未提交有效的同篇参照改写')
        if any(_words(p) in _words(text) for p in unit.get("lieflat_review", {}).get("mandatory_phrases", []) if _words(p)):
            raise ValueError(f'{unit["id"]} 仍照录了去 AI 味检测标记的表达，请换一种说法。')
        with closing(sqlite3.connect(self.path, timeout=20)) as db, db:
            db.execute("INSERT OR IGNORE INTO edits VALUES(?,?,?)",
                       (self.key, row["id"], json.dumps(row, ensure_ascii=False)))

    def reopen(self, rejection):
        reason = rejection["reason"]
        unit_ids = set(rejection.get("ids", re.findall(r"p\d+-s\d+", reason)))
        ids = [k for k in self.units if k in unit_ids]
        if not ids:
            paragraph_ids = set(re.findall(r"p\d+", reason))
            ids = [k for k, u in self.units.items() if u["paragraph_id"] in paragraph_ids]
        with closing(sqlite3.connect(self.path, timeout=20)) as db, db:
            if db.execute("INSERT OR IGNORE INTO rejections VALUES(?,?)",
                          (self.key, rejection["rejection_id"])).rowcount:
                db.executemany("DELETE FROM edits WHERE binding=? AND id=?", [(self.key, k) for k in ids or self.units])

    def prompt(self, unit):
        pid = unit["paragraph_id"]
        number = int(pid[1:])
        old = unit["old"]
        def rank(k):
            dialogue_mismatch = ("“" in old) != ("“" in self.references[k])
            return dialogue_mismatch, abs(int(k[1:]) - number) if k.startswith("p") else 0
        choices = sorted(self.references, key=rank)[:2]
        context = [self.paragraphs.get(f"p{number-1:04}", "")[-80:], self.paragraphs[pid],
                   self.paragraphs.get(f"p{number+1:04}", "")[:80]]
        return ("本轮只改指定片段。从给出的同篇通过段落中选一段参照，沿用原段的人称、说话人和叙述权限，保住人物口吻、台词意图、"
                "细节、数字和前后关系。若片段截在半句中间，请接回原处。自由选择说法。"
                '只输出 JSON 对象 {"id":"原编号","reference_id":"选中的参考编号","replacement":"改写正文"}。\n'
                + json.dumps({"本书约束": self.view.get("book_contract", {}),
                              "作者意见": self.view.get("author_feedback", ""), "相邻正文": context,
                              "同篇参考": {k:self.references[k] for k in choices},
                              "片段": unit}, ensure_ascii=False)), choices


async def run_resumable(node, ctx, view_path, view, identity):
    from ..engine import WorkflowEngine
    from .zhuque_rounds import PluginAdapter
    definition = ctx.node_def
    output_key = definition.output_variable
    output_name = await resolve_placeholders(definition.output_file_path, ctx.parameter_values, ctx.definition.variables, str(ctx.shared_ws))
    output = resolve_workspace_file_path(ctx.shared_ws, output_name)
    progress = RewriteProgress(view_path.with_name("rewrite-progress.sqlite3"), view, identity)
    history = ctx.node_state.rejection_history
    if history:
        progress.reopen(history[-1])
    existing = progress.rows()
    adapter = PluginAdapter(ctx, standalone=True)
    protected = view.get("book_contract", {}).get("protected_phrases", [])
    async def scan(texts, marks=None):
        return await adapter("local-tone", "", texts=texts, original_marks=marks or {}, protected_phrases=protected)
    marks = await scan({key: unit["old"] for key, unit in progress.units.items()})
    if existing:
        prior = await scan({k: row["replacement"] for k, row in existing.items()}, marks)
        for key, hits in prior.items():
            if hits:
                progress.invalidate(existing.pop(key))
    accumulated = None
    calls = []
    failures = {}
    consecutive_failures = 0
    params = {k:v for k,v in definition.node_params.items() if k not in
              ("resumable_rewrite_input", "first_message_source_variable", "json_output_schema", "json_repair_policy")}
    for key, unit in progress.units.items():
        if key in existing:
            continue
        local_review = {**unit.get("lieflat_review", {}), "mandatory_phrases":marks[key],
                        "guidance":"明确标记须保留原意、数字、人物口吻换个说法。"}
        try:
            for attempt in range(3):
                prompt, choices = progress.prompt({**unit, "lieflat_review":local_review})
                child = replace(definition, first_message=prompt, node_params=params, save_output_to_file=False, require_non_empty_output=True)
                result = await node.execute(replace(ctx, node_def=child))
                accumulated = WorkflowEngine._merge_token_usage(accumulated, result.token_usage)
                calls = WorkflowEngine._merge_token_usage_calls(calls, result.token_usage_calls)
                if result.status != "completed":
                    raise ValueError(result.error or result.status)
                raw = result.outputs[output_key].strip()
                if raw.startswith("```json\n") and raw.endswith("```"):
                    raw = raw[8:-3]
                row = json.loads(raw)
                if (not isinstance(row, dict) or set(row) != {"id","reference_id","replacement"} or row["id"] != key
                        or row["reference_id"] not in choices or not isinstance(row["replacement"], str)):
                    raise ValueError("片段编号、正文或引用与本次任务不符")
                hits = (await scan({key:row["replacement"]}, {key:marks[key]}))[key]
                if not hits:
                    progress.store(row)
                    break
                local_review["上一稿仍须换说法"] = hits
                if attempt == 2:
                    raise ValueError("本地校读仍有明确命中：" + "、".join(hits))
        except (KeyError, ValueError, TypeError) as exc:
            failures[key] = str(exc)
            consecutive_failures += 1
            if consecutive_failures >= 3:
                break
            continue
        consecutive_failures = 0
        logger.info("已保存逐段改写 %s (%s)，任务 %s", key, definition.id, ctx.task_id)
    rows = progress.rows()
    if len(rows) < len(progress.units):
        return NodeResult(status="failed", error=f"已保存 {len(rows)}/{len(progress.units)} 处，下次仅续写余项。{failures}",
                          session_id=ctx.node_state.session_id, token_usage=accumulated, token_usage_calls=calls)
    raw = json.dumps({"source_sha256":view["source_sha256"], "edits":[], "rewrites":[rows[k] for k in progress.units]}, ensure_ascii=False)
    atomic_write(output, raw.encode())
    return NodeResult(status="completed", summary=f"已完成 {len(rows)} 处同篇参照改写", session_id=ctx.node_state.session_id,
                      outputs={output_key:raw, "_output_file":str(output)}, token_usage=accumulated, token_usage_calls=calls)

