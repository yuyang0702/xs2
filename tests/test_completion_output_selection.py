import json
from types import SimpleNamespace
import pytest
from src.workflow.nodes.agent import AgentNode


def trajectory(content='```json\n{"chapters": []}\n```'):
    return [
        {"type": "user", "content": "plan"},
        {"type": "assistant", "content": content, "tool_calls": [{"id": "done", "function": {"name": "complete_task", "arguments": json.dumps({"status": "success", "artifact_path": ""})}}]},
        {"type": "tool", "tool_call_id": "done", "content": json.dumps({"success": True, "status": "success"})},
        {"type": "assistant", "content": "The outline is ready."},
    ]


def select(record):
    sm = SimpleNamespace(sessions={"s": SimpleNamespace(record=record)})
    return AgentNode._select_output(sm, "s", {"output_selection": "completion_tool_message", "json_required_fields": ["chapters"]})


def test_real_completion_trajectory():
    assert json.loads(select(trajectory())[0])["chapters"] == []


@pytest.mark.parametrize("content", ['broken', '{"wrong": []}', '{"chapters": []}\n{"chapters": [1]}'])
def test_invalid_or_multiple_documents_fail(content):
    assert select(trajectory(content))[1]


def test_old_completion_is_not_reused():
    assert select(trajectory() + [{"type": "user", "content": "retry"}, {"type": "assistant", "content": "summary"}])[1]


def test_tool_json_is_not_output():
    record = trajectory("")
    record[2]["content"] = '{"success": true, "status": "success", "chapters": []}'
    assert select(record)[1]


def test_ambiguous_completions_fail():
    assert select(trajectory() + trajectory()[1:])[1]


def test_failed_or_unmatched_tool_fails():
    record = trajectory()
    record[2]["tool_call_id"] = "other"
    assert select(record)[1]


def test_default_keeps_final_summary():
    sm = SimpleNamespace(sessions={"s": SimpleNamespace(record=trajectory())})
    assert AgentNode._select_output(sm, "s", {}) == ("The outline is ready.", "")


@pytest.mark.parametrize("result", [{"success": False, "status": "success"}, {"success": True, "status": "failed"}])
def test_rejected_completion_fails(result):
    record = trajectory()
    record[2]["content"] = json.dumps(result)
    assert select(record)[1]


def test_extra_json_message_is_ambiguous():
    record = trajectory()
    record.insert(1, {"type": "assistant", "content": '{"chapters": [1]}'})
    assert select(record)[1]


@pytest.mark.parametrize('disabled', [False, True])
def test_standalone_patch_is_rephrased_before_file_is_replaced(tmp_path, monkeypatch, disabled):
    import asyncio
    from src.workflow.definition import WorkflowDef, WorkflowNode
    from src.workflow.nodes import zhuque_rounds
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState

    target = tmp_path / 'patch.json'
    target.write_text('previous', encoding='utf-8')
    (tmp_path / 'source.json').write_text('{"source_body":"原段"}', encoding='utf-8')
    requests = []

    class Scanner:
        def __init__(self, ctx, *, standalone):
            assert standalone

        async def __call__(self, action, body, *, view, patch):
            assert action == 'local-patch' and view['source_body'] == '原段'
            return {'feedback':'标记原句' if patch['edits'] == [] else ''}

    class Manager:
        sessions = {}
        async def create_sub_session(self, **kwargs):
            assert target.read_text(encoding='utf8') == 'previous'
            requests.append(kwargs['task_description'])
            edits = [] if len(requests) == 1 else [{'replacement':'新说法'}]
            sid = str(len(requests))
            self.sessions[sid] = SimpleNamespace(record=trajectory(json.dumps({'edits':edits})))
            kwargs['on_auto_complete'](sid, 'done', 'success', '')
            return {'success':True, 'session_id':sid}

    monkeypatch.setattr(zhuque_rounds, 'PluginAdapter', Scanner)
    node = WorkflowNode(id='agent_pl', node_type='agent', first_message='改一段', save_output_to_file=True,
                        output_file_path='patch.json', node_params={'resumable_rewrite_input':'editor',
                        'output_selection':'completion_tool_message','json_repair_policy':'validate_only'})
    nodes = [node, WorkflowNode(id='script_local_candidate', node_type='script')] if disabled else [node]
    result = asyncio.run(AgentNode().execute(NodeContext(definition=WorkflowDef(workflow_id='one', nodes=nodes),
        node_def=node, node_state=NodeExecutionState(node_id=node.id), parameter_values={'editor':'source.json'},
        disabled_node_ids=frozenset({'script_local_candidate'}) if disabled else frozenset(),
        session_manager=Manager(), shared_ws=tmp_path)))
    assert result.status == 'completed', result.error
    assert len(requests) == 2 and '标记原句' in requests[-1]
    assert json.loads(target.read_text(encoding='utf8'))['edits'][0]['replacement'] == '新说法'


def test_plain_final_json_without_tool_succeeds():
    assert json.loads(select([{"type": "user", "content": "plan"}, {"type": "assistant", "content": '{"chapters": []}'}])[0]) == {"chapters": []}


@pytest.mark.parametrize("content,expected", [('broken', 'failed'), ('{"chapters": null}', 'failed'), ('```json\n{"chapters": []}\n```', 'completed')])
def test_file_gate_uses_selected_output(tmp_path, content, expected):
    import asyncio
    from src.workflow.definition import WorkflowDef, WorkflowNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    class Manager:
        sessions = {}
        async def create_sub_session(self, **kwargs):
            self.sessions['s'] = SimpleNamespace(record=trajectory(content))
            kwargs['on_auto_complete']('s', 'done', 'success', '')
            return {"success": True, "session_id": "s"}
    target = tmp_path / 'output.json'
    target.write_text('preserved', encoding='utf-8')
    node = WorkflowNode(id='outline', node_type='agent', first_message='plan', save_output_to_file=True,
                        output_file_path='output.json', node_params={"output_selection": "completion_tool_message", "json_required_fields": ["chapters"], "json_repair_policy": "validate_only", "json_output_schema": {"type": "object", "properties": {"chapters": {"type": "array"}}}})
    result = asyncio.run(AgentNode().execute(NodeContext(definition=WorkflowDef(workflow_id='test',nodes=[node]), node_def=node,
                          node_state=NodeExecutionState(node_id=node.id), session_manager=Manager(), shared_ws=tmp_path)))
    assert result.status == expected
    if expected == 'failed':
        assert target.read_text(encoding='utf-8') == 'preserved'
        assert result.outputs == {}
    else:
        assert json.loads(target.read_text(encoding='utf-8')) == {"chapters": []}


@pytest.mark.parametrize("text", ['{"chapters": null}', '{"chapters": []}', '{"chapters": [{"number": null}]}'])
def test_declared_schema_rejects_invalid_shapes(text):
    from src.workflow.output_selection import select_agent_output
    schema = {"type": "object", "required": ["chapters"], "properties": {"chapters": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["number"], "properties": {"number": {"type": "integer", "minimum": 1}}}}}}
    assert select_agent_output(trajectory(text), {"output_selection": "completion_tool_message", "json_output_schema": schema})[1]


@pytest.mark.parametrize(("constraint", "detail"), [
    ({"maxItems": 10}, "11 items, expected maxItems=10"),
    ({"contains": {"required": ["focus"]}}, "no item satisfies contains"),
])
def test_schema_array_error_does_not_echo_the_report(constraint, detail):
    from src.workflow.output_selection import select_agent_output

    report = {"expression_checks": [{"evidence": "original manuscript passage " * 300}] * 11}
    schema = {"type": "object", "properties": {"expression_checks": {"type": "array", **constraint}}}
    output, error = select_agent_output(trajectory(json.dumps(report)), {
        "output_selection": "completion_tool_message", "json_output_schema": schema,
    })

    assert not output
    assert "$.expression_checks" in error
    assert detail in error
    assert "original manuscript passage" not in error


@pytest.mark.parametrize("text", ['{"chapters": [], "x": NaN}', '{"chapters": [], "chapters": [1]}'])
def test_strict_json_rejects_constants_and_duplicate_keys(text):
    assert select(trajectory(text))[1]
