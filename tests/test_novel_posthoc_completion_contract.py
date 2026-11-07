import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext
from src.workflow.runtime_models import NodeExecutionState


def test_installed_plugin_posthoc_requires_final_file_output_instead_of_summary(tmp_path):
    path=Path(__file__).resolve().parents[2]/'DeterminFlow-Plugins/plugins/xs2-novel-flywheel/resources/workflows/post-hoc/definition.json'
    definition=json.loads(path.read_text(encoding='utf8'))
    for raw in [n for n in definition['nodes'] if n.get('node_type')=='agent' and n.get('save_output_to_file')]:
        node=WorkflowNode.from_dict({**raw,'first_message':'Return the structured report','system_prompt_template':'','output_file_path':'report.json'})
        class Manager:
            sessions={}
            async def create_sub_session(self,**kwargs):
                # A completion-only model response is possible when that tool
                # is advertised. Without it the same model delivers its JSON.
                record=[] if kwargs['enable_complete_node_task'] else [{'type':'assistant','content':'{"reports":[],"state":{}}'}]
                self.sessions['s']=SimpleNamespace(record=record)
                kwargs['on_auto_complete']('s','summary only','success','')
                return {'success':True,'session_id':'s'}
        result=asyncio.run(AgentNode().execute(NodeContext(definition=WorkflowDef(workflow_id='w',nodes=[node]),node_def=node,node_state=NodeExecutionState(node_id=node.id),session_manager=Manager(),shared_ws=tmp_path)))
        assert result.status=='completed',result.error
        assert json.loads((tmp_path/'report.json').read_text(encoding='utf8'))=={'reports':[],'state':{}}
