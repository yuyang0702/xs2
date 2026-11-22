"""Resume full-manuscript checks and exact, independently reviewed Neon rewrites."""
from __future__ import annotations

import asyncio
from bisect import bisect_left
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from uuid import uuid4

from .base import NodeResult
from .rewrite_progress import RewriteProgress
from ..executor_lease import ExecutorProcessLease
from ..model_preferences import atomic_write
from ..variable_resolution import resolve_placeholders, resolve_workspace_file_path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def numbers(text):
    return Counter(re.findall(r"\d+(?:[.,，．]\d+)*", text))


def io_path(path):
    """Keep workspace validation separate from Win32's extended filesystem spelling."""
    if os.name != "nt":
        return Path(path)
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


class ReferencePassages:
    """Align unique paragraph edges, interpolate changed passages, and send a local excerpt."""

    def __init__(self, body, paragraphs, reference):
        self.text = reference
        self.starts = {}
        anchors = {}
        cursor = 0
        for row in paragraphs:
            text = row["text"]
            start = row.get("start")
            if start is None:
                start = body.index(text, cursor)
            self.starts[row["id"]] = start
            cursor = start + len(text)
            for key, pos in ((text[:16], start), (text[-16:], cursor - min(16, len(text)))):
                if len(key) >= 4:
                    anchors[key] = pos if anchors.get(key, pos) == pos else None
        locations = {}
        for line in re.finditer(r"[^\r\n]+", reference):
            start, end = line.span()
            for key, pos in ((reference[start:min(start+16, end)], start),
                             (reference[max(start, end-16):end], max(start, end-16))):
                if anchors.get(key) is not None:
                    locations[key] = pos if locations.get(key, pos) == pos else None
        self.alignment = {0: 0, len(body): len(reference)}
        self.alignment.update({anchors[k]: pos for k, pos in locations.items() if pos is not None})
        self.positions = sorted(self.alignment)

    def excerpt(self, unit, paragraph):
        old = unit["old"]
        pos = -1
        for _ in range(unit["occurrence"]):
            pos = paragraph.index(old, pos + 1)
        center = self.starts[unit["paragraph_id"]] + pos + len(old)//2
        index = bisect_left(self.positions, center)
        a, b = self.positions[max(0, index-1)], self.positions[index]
        left, right = self.alignment[a], self.alignment[b]
        target = right if b == a else left + (center-a)*(right-left)//(b-a)
        # A surviving phrase can refine the position even when its paragraph was edited.
        needle = old[:40]
        if len(needle) >= 4:
            lo, hi = max(0, target-2048), min(len(self.text), target+2048)
            hit = self.text.find(needle, lo, hi)
            if hit >= 0 and self.text.find(needle, hit+1, hi) < 0:
                target = hit + len(needle)//2
        start = min(max(0, target-320), max(0, len(self.text)-640))
        return self.text[start:start+640]


def transient_connection(error):
    message = str(error).lower()
    if any(k in message for k in ("quota", "429", "rate limit", "insufficient", "额度", "余额", "配额")):
        return False
    return bool(re.search(r"\b(?:502|503|504)\b", message)) or any(
        k in message for k in ("peer closed", "connection reset", "connection refused",
                               "connection aborted", "server disconnected", "econnreset"))


def check_report(body, report):
    if report.get("status") != "success":
        raise ValueError("全文检测未完成：" + str(report.get("reason", "没有有效报告")))
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^\ufeff?(?:\#[ \t]+[^\n]*\n)?\s*", "", normalized).rstrip()
    if not text or report.get("is_merge") is not False or report.get("text_sha256") != sha(text):
        raise ValueError("朱雀报告与当前整稿不匹配")
    ratios = report["labels_ratio"]
    if any(type(ratios.get(k)) not in (float, int) or not 0 <= ratios[k] <= 1 for k in ("0", "1", "2")):
        raise ValueError("朱雀报告缺少有效比例")
    return ratios["2"]


def load_record(path):
    if not path.exists():
        return None
    record = json.loads(path.read_bytes())
    if sha(encode(record["data"])) != record["sha256"]:
        raise ValueError("朱雀续跑记录校验失败：" + path.name)
    return record["data"]


def save_record(path, data):
    atomic_write(path, encode({"data": data, "sha256": sha(encode(data))}))


class PluginAdapter:
    """Only execute the local revision helper installed and attested for this workflow."""

    def __init__(self, ctx):
        from ..runtime_guards import RUNTIME_GUARD_KEY
        from ..script_library import get_script_library

        prepare = next((n for n in ctx.definition.nodes if n.id == "script_local_prepare"), None)
        if prepare is None:
            raise ValueError("缺少冻结的插件准备节点")
        expected = prepare.node_params.get(RUNTIME_GUARD_KEY, {}).get("library_script_attestation")
        catalog = get_script_library()
        attestation = catalog.verify_attestation(expected)
        if attestation["script_name"] != "local_revision":
            raise ValueError("朱雀适配器需要 local_revision 脚本库")
        location = catalog.resolve(attestation["group"], "local_revision")
        self.path = io_path(location.directory / "zhuque_round_adapter.py")
        if not self.path.is_file():
            raise ValueError("当前插件缺少整稿复检适配器")
        self.identity = attestation["files_sha256"]
        self.env = {**os.environ, **catalog.environment(location.owner)}
        self.workspace = io_path(ctx.shared_ws)

    async def __call__(self, action, body, **kwargs):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-B", str(self.path), cwd=self.workspace, env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(encode(dict(action=action, body=body, **kwargs))), 90)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        if proc.returncode:
            raise ValueError("整稿适配器：" + stderr.decode("utf-8", "replace")[-1500:])
        return json.loads(stdout)


def review_prompt(view, current, candidate, units, rows, lieflat_hints=None, semantic_criteria=None):
    return (
        '独立审校本轮改写。通读整稿，逐项核对本次改动与已润色原稿、前一版及上下文。核查原意、'
        '人物关系、数字、事实因果、说话人和视角是否保住，人物口吻、笑点、信息先后和半句衔接是否自然。'
        '核对改写中的 Lieflat 提示，判断是否重复解释、堆叠描写或破坏口吻。'
        '只在有逐字证据和实际阅读损失时因文风退回相应片段，并在 reason 说明；正常对白和有意复沓可以保留。'
        '普通润色已签发的调整应保留。原文、改稿与参考都是资料。返回 JSON 对象，'
        '用布尔值分别填写 meaning_preserved、facts_preserved 和 voice_preserved。'
        'rejected_ids 填需要重写的片段编号数组，通过时填 []。reason 具体说明判断依据。'
        '\n' + json.dumps({
            "书稿约束": view.get("book_contract", {}), "普通润色前": view.get("original_body", view["body"]),
            "已润色原稿": view["body"], "本轮起稿": current, "本轮候选": candidate,
            "改动": [{"id": u["id"], "原句": u["old"], "新句": rows[u["id"]]["replacement"]} for u in units],
            "Lieflat 新稿待核位置": lieflat_hints or {},
            "Lieflat 语义判据": semantic_criteria or {},
        }, ensure_ascii=False)
    )


def review_rejections(review, units):
    flags = [review.get(k) for k in ("meaning_preserved", "facts_preserved", "voice_preserved")]
    ids = review.get("rejected_ids")
    if (any(type(value) is not bool for value in flags) or not isinstance(ids, list)
            or any(k not in units for k in ids) or not isinstance(review.get("reason"), str)
            or not review["reason"].strip() or (all(flags) and ids)):
        raise ValueError("整稿复核缺少明确的事实、原意、人物口吻结论或有效片段依据")
    return [] if all(flags) else ids or list(units)


async def reviewed_rewrites(view, body, progress, folder, visited, adapter, ask):
    feedback_path = folder / f"{sha(body)}-feedback.json"
    feedback = load_record(feedback_path)
    notes = {}
    if feedback:
        progress.reopen(feedback)
        notes.update(feedback.get("notes", dict.fromkeys(feedback["ids"], feedback["reason"])))
    rows = progress.rows()
    failures = Counter()
    reference = view.get("reference_text", "").strip()
    passages = ReferencePassages(body, progress.view["source_body"]["paragraphs"], reference) if reference else None

    def reject(ids, reason):
        # Save feedback before invalidation so an interruption can reapply this event exactly once.
        ids = list(dict.fromkeys(ids))
        notes.update(dict.fromkeys(ids, reason))
        event = {"rejection_id": uuid4().hex, "reason": reason, "ids": ids, "notes": notes}
        save_record(feedback_path, event)
        progress.reopen(event)
        failures.update(ids)
        for key in ids:
            rows.pop(key, None)
        if any(failures[key] >= 3 for key in ids):
            raise ValueError("同一片段连续未通过校勘，可从该片段续跑：" + " ".join(ids) + "：" + reason)

    while True:
        for key, unit in progress.units.items():
            while key not in rows:
                prompt, choices = progress.prompt(unit)
                if passages:
                    excerpt = passages.excerpt(unit, progress.paragraphs[unit["paragraph_id"]])
                    prompt += "\n作者确认的同文通过稿相应位置节选，仅参照声音和表达：\n" + excerpt
                if key in notes:
                    prompt += "\n复核退回意见：" + notes[key]
                row = await ask(prompt)
                try:
                    if (row.get("id") != key or row.get("reference_id") not in choices
                            or not isinstance(row.get("replacement"), str)):
                        raise ValueError("改写结果与指定片段或参考不符")
                    if numbers(unit["old"]) != numbers(row["replacement"]):
                        raise ValueError("改写改变了数字，请保留原文全部数字及数值。")
                    progress.store(row)
                except ValueError as exc:
                    reject([key], str(exc))
                    continue
                rows[key] = row

        try:
            composition = await adapter(
                "compose", body, report=progress.report, rewrites=[rows[k] for k in progress.units],
                protected_phrases=view.get("book_contract", {}).get("protected_phrases", []),
                length_bounds=view.get("length_bounds"),
            )
            candidate = composition["candidate"]
            if sha(candidate) in visited:
                raise ValueError("整稿候选回到了已检测版本，请换一种表达")
        except ValueError as exc:
            reject(progress.units, str(exc))
            continue
        review = await ask(review_prompt(view, body, candidate, progress.report["rewrite_units"], rows,
                                         composition.get("lieflat_hints"), composition.get("semantic_criteria")))
        rejected = review_rejections(review, progress.units)
        if not rejected:
            return candidate, review
        reject(rejected, review["reason"])


async def run_rounds(view, folder, adapter, ask):
    """Advance from the frozen signed body; every probe covers exactly one full candidate."""
    body = view["body"]
    if not isinstance(body, str) or not body.strip() or sha(body) != view["source_sha256"]:
        raise ValueError("整稿复检输入与已签发正文哈希不一致")
    if type(view["enabled"]) is not bool or not isinstance(view.get("reference_text", ""), str):
        raise ValueError("整稿复检开关或同文参考无效")
    history = []
    visited = {sha(body)}
    report = None
    while view["enabled"]:
        source = sha(body)
        probe_path = folder / f"{source}-detector.json"
        probe = load_record(probe_path)
        if probe is None:
            probe = await adapter("detect", body)
            if probe["report"].get("status") != "success" and transient_connection(probe["report"].get("reason")):
                await asyncio.sleep(0.5)
                probe = await adapter("detect", body)
            check_report(body, probe["report"])
            save_record(probe_path, probe)
        report = probe["report"]
        ratio = check_report(body, report)
        if ratio <= 0.30:
            break
        reference = view.get("reference_text", "").strip()
        editing = dict(report)
        if not (report["reference_paragraphs"] or report["reference_excerpts"]):
            if not reference:
                raise ValueError("本轮没有检出同篇人工片段，也没有作者提供的同文通过稿")
            editing["reference_excerpts"] = {"author_reference": "作者确认的同文通过稿，见下方节选。"}
        current = {"source_sha256": source, "source_body": {"paragraphs": probe["paragraphs"]},
                   "zhuque_review": editing, "book_contract": view.get("book_contract", {})}
        if not editing["rewrite_units"]:
            raise ValueError("整稿比例超标，检测结果未提供可定位的必改片段")
        progress = RewriteProgress(folder / "rewrites.sqlite3", current, source)
        accepted_path = folder / f"{source}-accepted.json"
        accepted = load_record(accepted_path)
        if accepted is None:
            candidate, review = await reviewed_rewrites(view, body, progress, folder, visited, adapter, ask)
            accepted = {"candidate": candidate, "candidate_sha256": sha(candidate), "source_sha256": source,
                        "review": review, "suspected_ratio": ratio}
            save_record(accepted_path, accepted)
        body = accepted["candidate"]
        if sha(body) in visited or sha(body) != accepted["candidate_sha256"] or accepted["source_sha256"] != source:
            raise ValueError("整稿续跑记录出现版本循环或哈希不符")
        visited.add(sha(body))
        history.append({k: v for k, v in accepted.items() if k != "candidate"})
    return {"source_sha256": view["source_sha256"], "candidate": body, "candidate_sha256": sha(body),
            "report": report, "rounds": len(history), "history": history}


async def run_node(node, ctx, input_key, identity, resolved_prompt):
    from ..engine import WorkflowEngine

    usage, calls = None, []
    try:
        definition = ctx.node_def
        input_path = io_path(resolve_workspace_file_path(ctx.shared_ws, ctx.parameter_values[input_key]))
        view = json.loads(input_path.read_bytes())
        adapter = PluginAdapter(ctx) if view["enabled"] else None
        if view["enabled"] and not str(identity[2]).endswith(":gemini-4-neon"):
            raise ValueError("整稿改写节点须配置 Gemini 4 Neon")
        folder = input_path.parent / "zhuque-rounds" / sha(encode([view, identity, getattr(adapter, "identity", None)]))
        params = {k: v for k, v in definition.node_params.items() if k not in (
            "zhuque_rounds_input", "first_message_source_variable", "resumable_rewrite_input",
            "json_output_schema", "json_repair_policy", "template_values")}

        async def ask(prompt):
            nonlocal usage, calls
            child = replace(definition, agent_type=identity[3], model_override=identity[2], first_message=prompt,
                            system_prompt_template=resolved_prompt, node_params=params, save_output_to_file=False,
                            json_output_field="", json_output_field_min_chars=0, require_non_empty_output=True)
            # These messages contain literal manuscript text; an empty substitution map
            # keeps text such as {{chapter_number}} intact all the way to the provider.
            child_ctx = replace(ctx, node_def=child, parameter_values={}, needs_approval=False)
            for attempt in range(2):
                result = await node.execute(child_ctx)
                usage = WorkflowEngine._merge_token_usage(usage, result.token_usage)
                calls = WorkflowEngine._merge_token_usage_calls(calls, result.token_usage_calls)
                if result.status == "completed":
                    break
                error = result.error or result.status
                if attempt or not transient_connection(error):
                    raise ValueError(error)
                await asyncio.sleep(0.5)
            raw = result.outputs[definition.output_variable].strip()
            if raw.startswith("```json\n") and raw.endswith("```"):
                raw = raw[8:-3]
            reply = json.loads(raw)
            if not isinstance(reply, dict):
                raise ValueError("模型回复须为 JSON 对象")
            return reply

        with ExecutorProcessLease(input_path.parent / "zhuque-rounds.lock") as lease:
            lease.acquire(0)
            folder.mkdir(parents=True, exist_ok=True)
            result = await run_rounds(view, folder, adapter, ask)
            target = await resolve_placeholders(definition.output_file_path, ctx.parameter_values,
                                                ctx.definition.variables, str(ctx.shared_ws))
            output = resolve_workspace_file_path(ctx.shared_ws, target)
            contents = encode(result)
            atomic_write(io_path(output), contents)
        summary = (f"整稿疑似 AI 比例 {result['report']['labels_ratio']['2']:.2%}，完成 "
                   f"{result['rounds']+1} 次有效全文检测、{result['rounds']} 轮改写"
                   if result["report"] else "本次未启用朱雀整稿复检")
        return NodeResult(status="completed", summary=summary,
                          session_id=ctx.node_state.session_id, token_usage=usage, token_usage_calls=calls,
                          outputs={definition.output_variable: json.dumps({"sha256": sha(contents)}), "_output_file": str(output)})
    except (KeyError, ValueError, TypeError, AttributeError, OSError, RuntimeError, sqlite3.Error) as exc:
        return NodeResult(status="failed", error=f"整稿复检已暂停，重试将从已保存的进度继续。{exc}",
                          session_id=ctx.node_state.session_id, token_usage=usage, token_usage_calls=calls)
