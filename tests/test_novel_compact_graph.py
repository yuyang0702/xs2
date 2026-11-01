"""Run the plugin's shipped novel graphs through the real host scheduler.

Node bodies are inert probes: these cases verify routing, convergence, loop
skips and retry state without model calls or writes to a novel workspace.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.workflow.definition import WorkflowDef, WorkflowRunRecord, WorkflowTask
from src.workflow.engine import WorkflowEngine
from src.workflow.nodes import BaseNodePlugin, NodeContext, NodeResult, registry


RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "DeterminFlow-Plugins/plugins/xs2-novel-flywheel/resources/workflows"
pytestmark = pytest.mark.skipif(not RESOURCE_ROOT.is_dir(), reason="Sibling xs2 novel plugin checkout is unavailable")

WORLD_AGENTS = ["agent_corelaws", "agent_spacetime", "agent_society", "agent_historyculture", "agent_existence", "agent_information"]
CHARACTER_AGENTS = ["agent_skeleton", "agent_belief", "agent_deep", "agent_deep", "agent_voice"]
MVP_PREP_AGENTS = {"agent_we", "agent_id", "agent_od", "agent_cm", "agent_se", "agent_trimmer"}
MVP_MULTI_AGENTS = {"agent_nw", "agent_aw", "agent_dw", "agent_dsw", "agent_iw", "agent_tw", "agent_si"}


def _run_graph(monkeypatch, workflow: str, values: dict[str, str | None]):
    data = json.loads((RESOURCE_ROOT / workflow / "definition.json").read_text(encoding="utf-8"))
    definition = WorkflowDef.from_dict(data)
    original_types = {node.id: node.node_type for node in definition.nodes}
    calls: list[str] = []

    class Probe(BaseNodePlugin):
        node_type = "novel_compact_graph_probe"

        async def execute(self, ctx: NodeContext) -> NodeResult:
            calls.append(ctx.node_def.id)
            outputs = {"character_names": '["阿禾", "小岚"]'} if ctx.node_def.id == "script_extract" else {}
            return NodeResult(status="completed", summary=ctx.node_def.id, outputs=outputs)

    monkeypatch.setitem(registry._plugins, Probe.node_type, Probe)
    for node in definition.nodes:
        node.node_type = Probe.node_type
    definition._rebuild_caches()
    parameters = {variable.key: variable.default for variable in definition.variables}
    for key, value in values.items():
        if value is None:
            parameters.pop(key, None)
        else:
            parameters[key] = value
    task = WorkflowTask(workflow_id=definition.workflow_id, status="running", parameter_values=parameters, snapshot_definition=definition.to_dict())
    monkeypatch.setattr("src.workflow.engine._current_engine", None)
    engine = WorkflowEngine(SimpleNamespace(sessions={}, main_session_id=""))

    async def no_save(*_args, **_kwargs):
        pass

    monkeypatch.setattr(engine, "_save_task_state", no_save)
    monkeypatch.setattr(engine, "_push_wf_task_update", lambda *_args: None)
    outcome = asyncio.run(engine._execute_plan_segment(
        definition=definition, task=task, execution_plan=definition.get_execution_plan(),
        disabled_ids=set(), shared_ws=None, parent_id="test-main", on_node_started=lambda _state: None,
        needs_approval=False, run_record=WorkflowRunRecord(workflow_id=definition.workflow_id),
    ))
    assert outcome == "completed"
    return task, calls, [node for node in calls if original_types[node] == "agent"]


@pytest.mark.parametrize("workflow,compact_agent,compact_script,standard_agents", [
    ("build", "agent_short_world", "script_short_world", WORLD_AGENTS),
    ("character", "agent_short_character", "script_short_character", CHARACTER_AGENTS),
])
def test_short_compact_preparation_executes_one_agent_and_skips_full_path(monkeypatch, workflow, compact_agent, compact_script, standard_agents):
    task, calls, agents = _run_graph(monkeypatch, workflow, {
        "preparation_mode": "compact", "conflict_plan_mode": "short_full", "character_names": "invalid-list-must-not-be-evaluated",
    })
    assert agents == [compact_agent]
    assert compact_script in calls
    assert all(task.node_states[node].status == "skipped" for node in set(standard_agents))
    assert not task.control_flow_state.get("loops")


@pytest.mark.parametrize("workflow,expected_agents", [("build", WORLD_AGENTS), ("character", CHARACTER_AGENTS)])
@pytest.mark.parametrize("values", [
    {},
    {"preparation_mode": "compact"},
    {"preparation_mode": None, "conflict_plan_mode": "short_full"},
    {"preparation_mode": "full", "conflict_plan_mode": "short_full"},
    {"preparation_mode": "compact", "conflict_plan_mode": "serial_arc"},
])
def test_legacy_full_and_long_preparation_keep_original_path(monkeypatch, workflow, expected_agents, values):
    _task, _calls, agents = _run_graph(monkeypatch, workflow, values)
    assert agents == expected_agents


def test_compact_single_chapter_keeps_common_context_writer_and_quality_tail(monkeypatch):
    task, calls, agents = _run_graph(monkeypatch, "mvp", {
        "preparation_mode": "compact", "conflict_plan_mode": "short_full", "chapter_number": "0001", "writer_type": "single",
    })
    assert agents == ["agent_sw"]
    assert calls[:4] == ["script_story_context", "script_sync_down", "script_smart_context", "script_short_context"]
    assert calls.index("script_short_context") < calls.index("agent_sw") < calls.index("script_si_post") < calls.index("script_check_originality")
    assert calls.count("agent_sw") == calls.count("script_si_post") == calls.count("script_check_originality") == 1
    assert all(task.node_states[node].status == "skipped" for node in MVP_PREP_AGENTS | MVP_MULTI_AGENTS)


@pytest.mark.parametrize("values", [
    {"preparation_mode": None, "writer_type": "single"},
    {"preparation_mode": "full", "writer_type": "single"},
    {"preparation_mode": "compact", "conflict_plan_mode": "serial_arc", "writer_type": "single"},
    {"preparation_mode": "compact", "chapter_number": "0002", "writer_type": "single"},
    {"preparation_mode": "compact", "writer_type": "muti"},
])
def test_mvp_defaults_later_chapters_and_multi_writer_preserve_standard_path(monkeypatch, values):
    task, calls, agents = _run_graph(monkeypatch, "mvp", {"conflict_plan_mode": "short_full", "chapter_number": "0001", **values})
    assert MVP_PREP_AGENTS <= set(agents)
    assert "script_short_context" not in calls
    assert calls.count("script_si_post") == calls.count("script_check_originality") == 1
    if values["writer_type"] == "muti":
        assert MVP_MULTI_AGENTS <= set(agents)
        assert "agent_sw" not in calls
        assert task.node_states["agent_sw"].status == "skipped"
    else:
        assert agents.count("agent_sw") == 1
        assert not (MVP_MULTI_AGENTS & set(agents))
