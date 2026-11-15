import asyncio
from types import SimpleNamespace

import pytest

from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.nodes import NodeContext, registry
from src.workflow.runtime_models import NodeExecutionState
from src.workflow.task_overrides import MODEL_PARAMS_OVERRIDE_KEY


@pytest.mark.parametrize('writer_id, slot, configured, short_context, short_definition, compact', [
    ('agent_dw', 2, True, 'cache/short/test-task.md', True, False),
    ('agent_sw', 0, False, 'cache/short/test-task.md', True, False),
    ('agent_sw', 0, True, '', True, False),
    ('agent_sw', 0, True, 'cache/short/test-task.md', False, False),
    ('agent_sw', 0, True, 'cache/short/test-task.md', True, True),
])
def test_rehearsal_uses_writer_route_and_returns_usage_and_file(
    tmp_path, monkeypatch, writer_id, slot, configured, short_context, short_definition, compact,
):
    from langchain_core.messages import AIMessage
    from src.agent import definition
    from src.core import llm_client
    from src.web import novel_plugin

    node = WorkflowNode(id=f'rehearse_{writer_id}', node_type='novel_rehearsal',
                        node_params={'writer_node': writer_id, 'slot': slot, 'compact_short_writer': configured})
    writer = WorkflowNode(id=writer_id, agent_type='writer', model_override='book:writer',
                          node_params={MODEL_PARAMS_OVERRIDE_KEY: {'temperature': 0.42}})
    workflow = WorkflowDef(workflow_id='test', nodes=[node, writer])
    calls = []

    class Model:
        metadata = {'determinflow_model_id': 'book:writer'}

        async def ainvoke(self, messages):
            calls.append(tuple(message.content for message in messages))
            return AIMessage(content='{"speech":"真这样？"}',
                             usage_metadata={'input_tokens': 10, 'output_tokens': 6, 'total_tokens': 16})

    def create(**kwargs):
        assert kwargs['model_override'] == 'book:writer'
        assert kwargs['model_params']['temperature'] == 0.42
        assert kwargs['provider_retries_enabled'] is False
        return Model()

    async def prepare(root, task, requested_writer, chapter, directory, requested_slot, style, call, *, model_identity, **options):
        assert (root, task, requested_writer, chapter, directory, requested_slot, style) == (
            tmp_path, 'test-task', writer_id, '0001', 'cache/multi/test-task', slot, 'adopted.md')
        assert options == ({'compact': True} if compact else {})
        assert model_identity
        assert await call('actor-1', 'own role', 'own input', lambda raw: raw) == '{"speech":"真这样？"}'
        return 'cache/multi/test-task/rehearsal.md', 1

    monkeypatch.setattr(novel_plugin, 'script_service', lambda _: SimpleNamespace(prepare_rehearsal=prepare))
    monkeypatch.setattr(definition, 'get_agent_definition', lambda _: SimpleNamespace(model=None, model_params={}))
    monkeypatch.setattr(llm_client, 'create_llm', create)
    runner = registry.get('novel_rehearsal')
    assert runner is not None
    result = asyncio.run(runner().execute(NodeContext(
        definition=workflow, node_def=node, node_state=NodeExecutionState(node_id=node.id),
        workflow_id='test', task_id='test-task', shared_ws=tmp_path,
        session_manager=SimpleNamespace(sessions={}),
        parameter_values={'multi_dir': 'cache/multi/test-task', 'chapter_number': '0001',
                          'short_context_file': short_context, 'single_writer_plan': '' if short_definition else None,
                          'pp_learning_context': '{{learning_context}}', 'learning_context': 'adopted.md'})))
    assert result.status == 'completed'
    assert result.outputs == {f'rehearsal_{writer_id}': 'cache/multi/test-task/rehearsal.md'}
    assert calls == [('own role', 'own input')]
    assert result.token_usage['book:writer']['total_tokens'] == 16
    assert len(result.token_usage_calls) == 1
