"""Opt-in first-message sources use the existing workflow value renderer."""
import asyncio
from types import SimpleNamespace

import pytest

from src.workflow.definition import WorkflowDef, WorkflowNode, WorkflowVariable
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext
from src.workflow.runtime_models import NodeExecutionState
from src.workflow.task_overrides import MODEL_PARAMS_OVERRIDE_KEY


def execute(root, params=None, values=None, variables=None):
    captured = []
    class Manager:
        sessions = {}
        async def create_sub_session(self, **kwargs):
            captured.append(kwargs)
            self.sessions['selected'] = SimpleNamespace(record=[{'type': 'assistant', 'content': 'done'}])
            kwargs['on_auto_complete']('selected', 'done', 'success', '')
            return {'success': True, 'session_id': 'selected'}
    node = WorkflowNode(id='work', node_type='agent', agent_type='existing-agent',
        first_message='Original {{topic}}\n\nKeep this spacing.  ', system_prompt_template='System {{topic}}',
        model_override='provider:existing', node_params={MODEL_PARAMS_OVERRIDE_KEY: {'temperature': 0.4}, **(params or {})})
    workflow = WorkflowDef(workflow_id='source-test', nodes=[node], variables=variables or [])
    result = asyncio.run(AgentNode().execute(NodeContext(definition=workflow, node_def=node,
        node_state=NodeExecutionState(node_id=node.id), session_manager=Manager(), shared_ws=root,
        parameter_values={'topic': 'context', **(values or {})})))
    return result, captured


def test_nonempty_text_source_replaces_only_first_message_and_uses_normal_nested_resolution(tmp_path):
    result, calls = execute(tmp_path, {'first_message_source_variable': 'request'}, {'request': 'Selected {{topic}}'})
    assert result.status == 'completed'
    assert calls[0]['task_description'] == 'Selected context'
    assert calls[0]['custom_prompt'] == 'System context'
    assert calls[0]['agent_type'] == 'existing-agent'
    assert calls[0]['model_override'] == 'provider:existing'
    assert calls[0]['model_params_override'] == {'temperature': 0.4}


def test_nonempty_file_source_uses_existing_file_rendering(tmp_path):
    (tmp_path / 'request.md').write_text('文件任务\n保留“引号”和换行。', encoding='utf-8')
    result, calls = execute(tmp_path, {'first_message_source_variable': 'request'}, {'request': 'request.md'},
        [WorkflowVariable(key='request', type='file')])
    assert result.status == 'completed'
    assert calls[0]['task_description'] == '文件任务\n保留“引号”和换行。'


@pytest.mark.parametrize('source', ['', '  \n', None])
def test_empty_source_falls_back_to_original_message_without_whitespace_changes(tmp_path, source):
    result, calls = execute(tmp_path, {'first_message_source_variable': 'request'}, {'request': source})
    assert result.status == 'completed'
    assert calls[0]['task_description'] == 'Original context\n\nKeep this spacing.  '


def test_no_configuration_preserves_original_even_when_source_like_variable_exists(tmp_path):
    result, calls = execute(tmp_path, values={'request': 'Should not select this'})
    assert result.status == 'completed'
    assert calls[0]['task_description'] == 'Original context\n\nKeep this spacing.  '


@pytest.mark.parametrize('config', ['unknown', 42, '{{request}}'])
def test_missing_or_invalid_configured_source_fails_before_creating_session(tmp_path, config):
    result, calls = execute(tmp_path, {'first_message_source_variable': config}, {'request': 'Selected'})
    assert result.status == 'failed'
    assert 'first_message_source_variable' in result.error
    assert calls == []


def test_selected_file_with_no_rendered_content_does_not_fall_back_to_unrelated_message(tmp_path):
    result, calls = execute(tmp_path, {'first_message_source_variable': 'request'}, {'request': 'missing.md'},
        [WorkflowVariable(key='request', type='file')])
    assert result.status == 'failed'
    assert calls == []
