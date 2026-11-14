import asyncio
from types import SimpleNamespace

from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.nodes import NodeContext, registry
from src.workflow.runtime_models import NodeExecutionState
from src.workflow.task_overrides import MODEL_PARAMS_OVERRIDE_KEY


def test_rehearsal_uses_writer_route_and_returns_usage_and_file(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessage
    from src.agent import definition
    from src.core import llm_client
    from src.web import novel_plugin

    node = WorkflowNode(id='rehearse_agent_dw', node_type='novel_rehearsal',
                        node_params={'writer_node': 'agent_dw', 'slot': 2})
    writer = WorkflowNode(id='agent_dw', agent_type='writer', model_override='book:writer',
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

    async def prepare(root, task, writer_id, chapter, directory, slot, style, call, *, model_identity):
        assert (root, task, writer_id, chapter, directory, slot, style) == (
            tmp_path, 'test-task', 'agent_dw', '0001', 'cache/multi/test-task', 2, 'adopted.md')
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
                          'pp_learning_context': '{{learning_context}}', 'learning_context': 'adopted.md'})))
    assert result.status == 'completed'
    assert result.outputs == {'rehearsal_agent_dw': 'cache/multi/test-task/rehearsal.md'}
    assert calls == [('own role', 'own input')]
    assert result.token_usage['book:writer']['total_tokens'] == 16
    assert len(result.token_usage_calls) == 1
