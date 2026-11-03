import json
from types import SimpleNamespace

from src.web.novel_progress import progress


def test_progress_forwards_bound_task_and_measured_usage_only(tmp_path):
    root = tmp_path / 'book'
    root.mkdir()
    flows = tmp_path / 'workflows'
    folder = flows / 'custom-mvp/tasks'
    folder.mkdir(parents=True)
    record = {'call_id': 'a', 'model_id': 'fixture:writer', 'total_tokens': 23}
    task = {'workflow_id': 'custom-mvp', 'task_id': 'one', 'workspace_override': str(root),
            'node_states': {
                'writer': {'status': 'completed', 'token_usage_calls': [record],
                           'child_states': {'same': {'status': 'completed', 'token_usage_calls': [record]}}},
                'skipped': {'status': 'skipped', 'token_usage_calls': [
                    {'call_id': 'skipped', 'model_id': 'fixture:unused', 'total_tokens': 99}]},
            }}
    (folder / 'one.json').write_text(json.dumps(task))
    (folder / 'other.json').write_text(json.dumps({**task, 'task_id': 'other', 'workspace_override': str(tmp_path / 'other')}))
    (folder / 'unbound.json').write_text(json.dumps({**task, 'task_id': 'unbound', 'workspace_override': None,
                                                    'status': 'failed', 'error': 'foreign detail'}))
    state = {'refs': {'mvp': {'workflow_id': 'custom-mvp', 'task_id': 'one'},
                      'polish': {'workflow_id': 'custom-mvp', 'task_id': 'other'},
                      'reader-sim': {'workflow_id': 'custom-mvp', 'task_id': 'unbound'},
                      'post-hoc': {'workflow_id': 'custom-mvp', 'task_id': '../tasks/one'}}}

    def project(book, manifest, tasks, usages, *, selected, include_details, archived):
        assert book == root and manifest is state
        assert selected == '0002' and include_details and archived == {}
        assert tasks == {'mvp': task, 'reader-sim': {'status': 'failed'}}
        assert usages == {'mvp': {'basis': 'ledger', 'models': ['fixture:writer'], 'total_tokens': 23, 'call_count': 1}}
        return {'result': 'projected'}

    result = progress(root, state, flows, chapter='0002',
                      service=SimpleNamespace(project_progress=project, chapter_id=lambda value: value.zfill(4)))
    assert result == {'result': 'projected'}


def test_archived_chapter_keeps_usage_for_the_displayed_bookwide_export(tmp_path):
    root = tmp_path / 'book'
    root.mkdir()
    flows = tmp_path / 'workflows'
    workflow = flows / 'custom-export'
    folder = workflow / 'tasks'
    folder.mkdir(parents=True)
    (workflow / '.extension.json').write_text(json.dumps({'owner': 'xs2-novel-flywheel', 'local_id': 'export'}))
    for task_id, chapter, calls in [('current-export', '', [31]), ('archived-export', '0001', [8, 13])]:
        task = {'workflow_id': workflow.name, 'task_id': task_id, 'workspace_override': str(root),
                'parameter_values': {'chapter_number': chapter}, 'status': 'completed',
                'node_states': {'exporter': {'status': 'completed', 'token_usage_calls': [
                    {'call_id': f'{task_id}-{index}', 'model_id': f'fixture:{task_id}', 'total_tokens': total}
                    for index, total in enumerate(calls)
                ]}}}
        (folder / f'{task_id}.json').write_text(json.dumps(task))
    state = {'values': {'chapter_number': '0002'},
             'refs': {'export': {'workflow_id': workflow.name, 'task_id': 'current-export'}}}

    def project(_book, _manifest, tasks, usages, **_options):
        return {'task_id': tasks['export']['task_id'], 'usage': usages['export']}

    result = progress(root, state, flows, chapter='0001',
                      service=SimpleNamespace(project_progress=project, chapter_id=lambda value: value.zfill(4)))
    assert result == {'task_id': 'current-export', 'usage': {'basis': 'ledger',
        'models': ['fixture:current-export'], 'total_tokens': 31, 'call_count': 1}}


def test_progress_route_checks_owner_and_never_resolves_invalid_workspace(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src import config
    from src.core.workspace_manager import WorkspaceManager
    from src.web import novel_routes

    monkeypatch.setattr(config, 'BASE_DIR', tmp_path)
    workspace_manager = WorkspaceManager(str(tmp_path / 'data/workspaces'))
    manager = SimpleNamespace(_ws_manager=workspace_manager, get_workflow_owner=lambda _: 'xs2-novel-flywheel')
    app = FastAPI()
    app.state.workflow_manager = manager
    app.include_router(novel_routes.router)
    client = TestClient(app)
    missing = tmp_path / 'data/workspaces/books/not-created'
    for workspace, status in [(str(missing), 404), ('../../outside', 400), ('', 400)]:
        response = client.get('/api/novel-console/progress', params={'workflow_id': 'custom-build', 'workspace': workspace})
        assert response.status_code == status, response.text
    assert not missing.exists()
    manager.get_workflow_owner = lambda _: 'other-plugin'
    assert client.get('/api/novel-console/progress', params={'workflow_id': 'foreign', 'workspace': str(missing)}).status_code == 400
