import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from src.workflow.definition import WorkflowNode
from src.workflow.nodes import zhuque_rounds as rounds
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext, NodeResult


class Detector:
    identity = "installed-helper"

    def __init__(self, ratios, *, references=True):
        self.ratios = iter(ratios)
        self.probes = []
        self.references = references

    async def __call__(self, action, body, **data):
        if action == "compose":
            candidate = body
            for u, r in zip(data["report"]["rewrite_units"], data["rewrites"]):
                candidate = candidate.replace(u["old"], r["replacement"], 1)
            return {"candidate": candidate}
        assert action == "detect"
        self.probes.append(body)
        ratio = next(self.ratios)
        if isinstance(ratio, str):
            return {"report": {"status": "unavailable", "reason": ratio}}
        rows = [{"id": f"p{i:04d}", "text": p} for i, p in enumerate(body.split("\n\n"), 1)]
        report = {"is_merge": False, "text_sha256": rounds.sha(body), "status": "success",
                  "labels_ratio": {"0": 1 - ratio, "1": 0, "2": ratio}, "reference_excerpts": {},
                  "reference_paragraphs": [rows[-1]["id"]] if self.references else [],
                  "rewrite_units": [{"id": r["id"]+"-s1", "old": r["text"], "occurrence": 1,
                                     "paragraph_id": r["id"]} for r in rows[:-1]]}
        return {"report": report, "paragraphs": rows}


PASSED = {"meaning_preserved": True, "facts_preserved": True, "voice_preserved": True,
          "rejected_ids": [], "reason": "核过原稿与候选中的对话、数字和上下文。"}
BODY = "关掉2盏灯。\n\n把门带上。\n\n我再睡一会儿。"


def setup(tmp_path, detector, monkeypatch, reference="", body=BODY):
    view = {"enabled": True, "body": body, "original_body": body, "source_sha256": rounds.sha(body),
            "reference_text": reference}
    (tmp_path/"source.json").write_text(json.dumps(view), encoding="utf8")
    definition = WorkflowNode(id="rounds", node_params={"zhuque_rounds_input": "source"},
                              agent_type="writer", model_override="lingsuan-google:gemini-4-neon",
                              output_variable="receipt", output_file_path="result.json", save_output_to_file=True)
    ctx = NodeContext(definition=SimpleNamespace(variables=[]), node_def=definition, shared_ws=tmp_path,
                      node_state=SimpleNamespace(session_id=""), parameter_values={"source": "source.json"},
                      task_id="task-test")
    monkeypatch.setattr(rounds, "PluginAdapter", lambda _: detector)
    written = []
    reviews = []

    class Writer(AgentNode):
        replies = {}
        review_results = []

        async def execute(self, ctx):
            if "zhuque_rounds_input" in ctx.node_def.node_params:
                return await super().execute(ctx)
            assert ctx.parameter_values == {}
            prompt = ctx.node_def.first_message
            if prompt.startswith("独立审校"):
                reviews.append(json.loads(prompt.split("\n", 1)[1]))
                response = self.review_results.pop(0) if self.review_results else PASSED
            else:
                packet, _ = json.JSONDecoder().raw_decode(prompt.split("\n", 1)[1])
                key = packet["片段"]["id"]
                written.append((key, prompt))
                old = packet["片段"]["old"]
                response = {"id": key, "reference_id": next(iter(packet["同篇参考"])),
                            "replacement": "请" + old}
                if self.replies.get(key):
                    value = self.replies[key].pop(0)
                    if isinstance(value, Exception):
                        return NodeResult(status="failed", error=str(value))
                    response["replacement"] = value
            return NodeResult(status="completed", outputs={"receipt": json.dumps(response)})

    writer = Writer()
    return lambda: asyncio.run(writer.execute(ctx)), writer, written, reviews


def test_quota_resume_multiple_whole_probes_equality_and_repeat(tmp_path, monkeypatch):
    detector = Detector([.8, .5, "HTTP 429", .30])
    run, writer, written, reviews = setup(tmp_path, detector, monkeypatch, "作者同文通过稿")
    writer.replies["p0002-s1"] = [ValueError("quota")]
    assert "quota" in run().error
    assert not (tmp_path/"result.json").exists()
    assert "429" in run().error
    result = run()
    assert result.status == "completed" and run().outputs == result.outputs
    assert "30.00%" in result.summary and "3 次有效全文检测、2 轮改写" in result.summary
    saved = (tmp_path/"result.json").read_bytes()
    assert json.loads(result.outputs["receipt"]) == {"sha256": rounds.sha(saved)}
    data = json.loads(saved)
    assert data["rounds"] == len(reviews) == 2
    assert data["candidate"].startswith("请请关掉2盏灯。")
    assert detector.probes == [BODY, reviews[0]["本轮候选"], data["candidate"], data["candidate"]]
    assert [k for k, _ in written] == ["p0001-s1", "p0002-s1", "p0002-s1", "p0001-s1", "p0002-s1"]
    assert all("作者同文通过稿" in p for _, p in written)
    assert all(r["普通润色前"] == BODY for r in reviews)


def test_numeric_and_semantic_rejection_reopen_only_returned_units(tmp_path, monkeypatch):
    detector = Detector([.31, .0], references=False)
    run, writer, written, reviews = setup(tmp_path, detector, monkeypatch, "已确认的同文参考。")
    writer.replies["p0001-s1"] = ["关掉3盏灯。"]
    writer.review_results.append(dict(PASSED, voice_preserved=False, reason="接不上门外人的声音", rejected_ids=["p0002-s1"]))
    assert run().status == "completed"
    assert [k for k, _ in written] == ["p0001-s1", "p0001-s1", "p0002-s1", "p0002-s1"]
    assert "author_reference" in written[-1][1] and "接不上门外人的声音" in written[-1][1]
    assert len(reviews) == len(detector.probes) == 2


def test_cycle_retries_its_current_round_without_reprobing(tmp_path, monkeypatch):
    detector = Detector([.8, .6, .1])
    run, writer, written, _ = setup(tmp_path, detector, monkeypatch)
    writer.replies.update({"p0001-s1": ["熄掉2盏灯。", "关掉2盏灯。"],
                           "p0002-s1": ["顺手关门。", "把门带上。"]})
    assert run().status == "completed" and len(detector.probes) == 3 and len(written) == 6


def test_persistent_rejection_stops_then_resumes_only_one_unit(tmp_path, monkeypatch):
    detector = Detector([.7, .29])
    run, writer, written, reviews = setup(tmp_path, detector, monkeypatch)
    writer.review_results.extend([dict(PASSED, meaning_preserved=False, reason="门开关之意相反", rejected_ids=["p0002-s1"])]*3)
    assert "连续未通过" in run().error and not (tmp_path/"result.json").exists()
    assert len(detector.probes) == 1 and len(reviews) == 3
    assert run().status == "completed"
    assert [k for k, _ in written].count("p0001-s1") == 1
    assert [k for k, _ in written].count("p0002-s1") == 4
    assert "门开关之意相反" in written[-1][1]


def test_transient_transport_retries_once_and_quota_never_auto_retries(tmp_path, monkeypatch):
    detector = Detector(["HTTP 502", .9, .1])
    run, writer, written, _ = setup(tmp_path, detector, monkeypatch)
    writer.replies["p0001-s1"] = [ValueError("peer closed"), ValueError("peer closed")]
    writer.replies["p0002-s1"] = [ValueError("HTTP 429, quota, peer closed")]
    assert "peer closed" in run().error and len(written) == 2
    assert "429" in run().error and [k for k,_ in written].count("p0002-s1") == 1
    assert run().status == "completed" and detector.probes[:2] == [BODY, BODY]


def test_long_reference_matches_unchanged_neighbors_and_limits_excerpt(tmp_path, monkeypatch):
    center = "靠码头拴着船。"
    source = "堤岸的那头响了一声。\n\n{{source}}小船开了。\n\n柜台里压着一封信。"
    reference = "首章不可重复！" * 1500 + "\n堤岸的那头响了一声。\n" + center + "\n柜台里压着一封信。\n" + "附录不可重复！"*3000
    run, _, written, reviews = setup(tmp_path, Detector([.8, .3]), monkeypatch, reference, source)
    assert run().status == "completed"
    selected_prompt = dict(written)["p0002-s1"]
    assert center in selected_prompt and "{{source}}" in selected_prompt and len(selected_prompt) < 1700
    assert reference not in str(reviews) and center not in str(reviews)
    assert "{{source}}" in reviews[0]["本轮候选"]


def test_unaligned_reference_uses_proportional_neighborhood():
    body = "一" * 1000
    ref = "甲"*4500 + "窗前的钟" * 250 + "乙"*4500
    unit = {"paragraph_id": "p0001", "old": "一", "occurrence": 500}
    passages = rounds.ReferencePassages(body, [{"id":"p0001", "text":body, "start":0}], ref)
    excerpt = passages.excerpt(unit, body)
    assert len(excerpt) == 640 and "窗前的钟" in excerpt and "甲" not in excerpt and "乙" not in excerpt


@pytest.mark.skipif(os.name != "nt", reason="Windows long-path regression")
def test_long_windows_path_checkpoints_sqlite_and_publication(tmp_path, monkeypatch):
    ordinary = tmp_path / ("工作区"*24) / ("长书名"*24) / ("任务名"*24) / ("子目录"*20)
    extended = rounds.io_path(ordinary)
    extended.mkdir(parents=True)
    run, _, _, _ = setup(extended, Detector([.78, .3]), monkeypatch)
    result = run()
    assert result.status == "completed", result.error
    assert run().outputs == result.outputs
    assert json.loads((extended/"result.json").read_bytes())["rounds"] == 1
    assert len(str(ordinary)) > 260 and list(extended.rglob("rewrites.sqlite3"))


def test_missing_references_stops_and_zero_rounds_passes(tmp_path, monkeypatch):
    detector = Detector([.9], references=False)
    run, _, written, _ = setup(tmp_path, detector, monkeypatch)
    assert "没有作者提供" in run().error and not written
    other = tmp_path / "passed"
    other.mkdir()
    run, _, written, reviews = setup(other, Detector([.3]), monkeypatch)
    assert run().status == "completed" and not written and not reviews
    assert json.loads((other/"result.json").read_bytes())["rounds"] == 0


@pytest.mark.parametrize("ratio", [True, float("nan"), 1.1])
def test_invalid_probe_never_passes(ratio):
    report = {"status": "success", "is_merge": False, "text_sha256": rounds.sha(BODY),
              "labels_ratio": {"0": 0, "1": 0, "2": ratio}}
    with pytest.raises(ValueError, match="比例"):
        rounds.check_report(BODY, report)
    report["text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="不匹配"):
        rounds.check_report(BODY, report)
