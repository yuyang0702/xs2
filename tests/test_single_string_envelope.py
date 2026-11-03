import asyncio
import json
from types import SimpleNamespace

import pytest
from src.workflow.output_repair import prepare_json_file_output


def adapt(text, policy='safe_repair_then_retry', field='body'):
    return asyncio.run(prepare_json_file_output(raw_output=text,
        node_params={'json_single_string_field': field, 'json_repair_policy': policy}, output_file_path='output.json'))


def test_known_single_string_frame_preserves_quotes_controls_and_existing_escapes():
    raw = '{"body":"她说"好"。\n下一行\\n引号\\"与反斜线\\\\。"}'
    result = adapt(raw)
    assert result['success']
    assert json.loads(result['text']) == {'body': '她说"好"。\n下一行\n引号"与反斜线\\。'}
    assert 'single_string_envelope' in result['meta']['_json_repair_applied']


@pytest.mark.parametrize('raw', ['{"body":"ok","extra":1}', '{"body":5}', '{"other":"ok"}',
    '{"body":"one","body":"two"}', '{"body":"x"} {"body":"y"}', '{"body":"truncated',
    '{"body":"x\\q"}', '{"body":"x {"nested":1} y"}', '{"body":"x ["one"] y"}',
    'prefix {"body":"x"}', '```json\n{"body":"x"}\n```\n```json\n{"body":"y"}\n```'])
def test_ambiguous_or_noncontract_output_is_rejected(raw):
    assert not adapt(raw)['success']


@pytest.mark.parametrize('policy', ['validate_only', 'retry_only', 'none'])
def test_strict_policies_never_repair_known_frame(policy):
    assert not adapt('{"body":"she said "yes""}', policy)['success']


def test_default_safe_repair_does_not_gain_the_adapter():
    result = asyncio.run(prepare_json_file_output(raw_output='{"body":"she said "yes""}',
        node_params={}, output_file_path='output.json'))
    assert not result['success']


def test_valid_single_field_and_optional_whole_fence():
    assert json.loads(adapt('{"body":"valid {brace} and [brackets]"}')['text']) == {'body':'valid {brace} and [brackets]'}
    assert json.loads(adapt('```json\n{"text":"a "quote""}\n```', field='text')['text']) == {'text':'a "quote"'}


def test_actual_agent_saves_adapted_body_and_output_variable_without_model_changes(tmp_path):
    from src.workflow.definition import WorkflowDef,WorkflowNode
    from src.workflow.nodes.agent import AgentNode
    from src.workflow.nodes.base import NodeContext
    from src.workflow.runtime_models import NodeExecutionState
    captured=[]
    class Manager:
        sessions={}
        async def create_sub_session(self,**kwargs):
            captured.append(kwargs);self.sessions['s']=SimpleNamespace(record=[{'type':'assistant','content':'{"body":"她说"好"。\n结束。"}'}])
            kwargs['on_auto_complete']('s','done','success','');return {'success':True,'session_id':'s'}
    n=WorkflowNode(id='a',node_type='agent',first_message='task',model_override='existing:model',save_output_to_file=True,
        output_file_path='output.json',output_variable='answer',node_params={'json_single_string_field':'body'})
    result=asyncio.run(AgentNode().execute(NodeContext(definition=WorkflowDef(workflow_id='w',nodes=[n]),node_def=n,
        node_state=NodeExecutionState(node_id='a'),session_manager=Manager(),shared_ws=tmp_path)))
    assert result.status=='completed'
    assert json.loads((tmp_path/'output.json').read_text(encoding='utf-8'))=={'body':'她说"好"。\n结束。'}
    assert result.outputs['answer']==(tmp_path/'output.json').read_text(encoding='utf-8')
    assert captured[0]['model_override']=='existing:model'
