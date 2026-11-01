"""Task query fallbacks must retain the persisted snapshot's true provenance."""
import json

from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.runtime_models import NodeExecutionState, WorkflowTask
from src.workflow.task_queries import TaskQueryMixin


def test_task_query_serializes_snapshot_provenance_separately_from_current_fallback(tmp_path):
    current = WorkflowDef(workflow_id='example', nodes=[
        WorkflowNode(id='review', label='Current edited label'),
        WorkflowNode(id='compact-new', label='New compact preparation'),
    ])
    (tmp_path / 'definition.json').write_text(json.dumps(current.to_dict()), encoding='utf-8')
    legacy = WorkflowTask(task_id='legacy', workflow_id='example', status='running',
                          node_states={'review': NodeExecutionState(node_id='review', status='running')})
    historical = WorkflowDef(workflow_id='example', nodes=[WorkflowNode(id='review', label='Original label')])
    newer = WorkflowTask(task_id='snapshot', workflow_id='example', status='running',
                         snapshot_definition=historical.to_dict(), node_states=legacy.node_states)

    class Queries(TaskQueryMixin):
        def _load_task(self, _workflow_id, task_id):
            return {'legacy': legacy, 'snapshot': newer}[task_id]

        def _resolve_wf_dir(self, _workflow_id):
            return tmp_path

    query = Queries()
    before = (tmp_path / 'definition.json').read_bytes()
    fallback = query.get_task_with_definition('example', 'legacy')
    saved = query.get_task_with_definition('example', 'snapshot')
    assert fallback['definition']['nodes'][1]['id'] == 'compact-new'
    assert fallback['task']['snapshot_definition'] is None
    assert fallback['task']['node_states']['review']['status'] == 'running'
    assert saved['definition']['nodes'][0]['label'] == 'Original label'
    assert saved['task']['snapshot_definition']['nodes'][0]['label'] == 'Original label'
    assert len(saved['task']['snapshot_definition']['nodes']) == 1
    assert legacy.snapshot_definition is None
    assert newer.snapshot_definition == historical.to_dict()
    assert (tmp_path / 'definition.json').read_bytes() == before
