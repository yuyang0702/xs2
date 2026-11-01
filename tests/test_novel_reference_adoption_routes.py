"""Host boundaries for plugin-owned, durable reference adoption."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.workspace_manager import WorkspaceManager
from src.extension_host.resource_ids import ResourceIdResolver, build_resource_id_plan


@pytest.fixture
def control(tmp_path, monkeypatch):
    from src import config
    from src.web import novel_reference_adoption_routes as routes
    monkeypatch.setattr(config, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    root = tmp_path / 'data/workspaces/books/my book'
    root.mkdir(parents=True)
    project = {'_revision': 2, 'mode': 'short', 'values': {'premise': '本书定位'}, 'refs': {}}
    (root / '.novel-project.json').write_text(json.dumps(project), encoding='utf-8')
    manager = SimpleNamespace(_ws_manager=WorkspaceManager(str(tmp_path / 'data/workspaces')),
        get_workflow_execution_policy=lambda _: 'public', is_workflow_owner_enabled=lambda _: True,
        list_workflows=lambda: [{'workflow_id': 'custom-build'}, {'workflow_id': 'custom-novel-advisor'}])
    resolver = ResourceIdResolver()
    resolver.register(build_resource_id_plan('xs2-novel-flywheel', 'custom', {'workflows': ['build', 'novel-advisor']}))
    extensions = SimpleNamespace(is_running=lambda _: True, resource_resolver=resolver)
    entry = {'id': str(uuid4()), 'purpose': 'advisor', 'status': 'completed', 'question': '本书创意',
             'configuration_base': {'mode': 'short', 'values': {'premise': '本书定位'}}}
    calls = []
    jobs = SimpleNamespace(start=lambda path, request_id, payload: calls.append((path, payload)) or
        {'id': request_id, 'status': 'checking'}, get=lambda path, request_id: {'id': request_id, 'status': 'applied'},
        latest=lambda path: {'id': 'latest', 'status': 'checking'})
    monkeypatch.setattr(routes, '_adoption_jobs', lambda request: jobs)
    monkeypatch.setattr(routes, '_assistant_jobs', lambda request: SimpleNamespace(history=lambda path: [entry]))
    monkeypatch.setattr(routes, '_available_assistant_workflow', lambda *args: 'custom-novel-advisor')
    monkeypatch.setattr(routes, '_selected_model', lambda *args: 'provider:adviser')
    monkeypatch.setattr(routes, 'ensure_idle', lambda *args: None)
    app = FastAPI()
    app.state.workflow_manager = manager
    app.state.extension_manager = extensions
    app.state.novel_automation = SimpleNamespace(has_active=lambda path: False)
    app.include_router(routes.router)
    from src.web.workflow_routes import router as workflow_router
    app.include_router(workflow_router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, root=root, entry=entry, calls=calls, jobs=jobs, app=app, project=project)


def body(c, **updates):
    return {'workflow_id': 'custom-build', 'workspace': str(c.root), 'entry_id': c.entry['id'],
            'request_id': str(uuid4()), 'expected_revision': 2, **updates}


def test_start_uses_saved_adviser_and_book_not_client_proposals(control):
    before = (control.root / '.novel-project.json').read_bytes()
    response = control.client.post('/api/novel-console/reference-adoption', json=body(control,
        project={'values': {'premise': 'forged'}}, recommendations=[{'library_id': 'forged'}]))
    assert response.status_code == 200, response.text
    payload = control.calls[0][1]
    assert payload['entry_id'] == control.entry['id']
    assert payload['project'] == control.project
    assert payload['_model_override'] == 'provider:adviser'
    assert (control.root / '.novel-project.json').read_bytes() == before


def test_start_rejects_stale_settings_incomplete_adviser_and_busy_book(control):
    response = control.client.post('/api/novel-console/reference-adoption', json=body(control, expected_revision=1))
    assert response.status_code == 409
    control.entry['status'] = 'running'
    assert control.client.post('/api/novel-console/reference-adoption', json=body(control)).status_code == 409
    control.entry['status'] = 'completed'
    control.app.state.novel_automation.has_active = lambda path: True
    assert control.client.post('/api/novel-console/reference-adoption', json=body(control)).status_code == 409
    assert not control.calls


def test_status_latest_and_bad_workspace_never_fall_back(control):
    query = {'workflow_id': 'custom-build', 'workspace': str(control.root), 'request_id': str(uuid4())}
    assert control.client.get('/api/novel-console/reference-adoption', params=query).json()['job']['status'] == 'applied'
    assert control.client.get('/api/novel-console/reference-adoption/latest', params=query).json()['job']['id'] == 'latest'
    for workspace in ['', str(control.root / '..' / 'other'), 'C:/outside-book']:
        assert control.client.post('/api/novel-console/reference-adoption', json=body(control, workspace=workspace)).status_code in {400, 404}
    assert not control.calls


def test_exact_merge_keeps_distinct_sources_with_identical_names():
    from src.web.novel_library import enrich_candidates
    a = {'source': {'text_sha256': 'a'}, 'candidates': [{'candidate_id': 'a-rule', 'mechanism': '潜台词'}]}
    b = {'source': {'text_sha256': 'b'}, 'candidates': [{'candidate_id': 'b-rule', 'mechanism': '潜台词'}]}
    merged = enrich_candidates(a, b, exact_ids=True)
    assert [item['candidate_id'] for item in merged['candidates']] == ['a-rule', 'b-rule']


def test_existing_pending_task_cannot_start_during_adoption(control):
    manager = control.app.state.workflow_manager
    manager.get_task = lambda *args: {'workspace_override': str(control.root)}
    async def unexpected_run(*args, **kwargs):
        pytest.fail('task started while compatibility analysis was pending')
    manager.run_task = unexpected_run
    control.app.state.novel_reference_adoption_jobs = SimpleNamespace(has_active=lambda root: True)
    response = control.client.post('/api/workflows/custom-build/tasks/old-task/run')
    assert response.status_code == 409, response.text


def test_latest_on_new_book_is_empty_without_creating_workspace(control):
    fresh = control.root.parent / 'new book'
    response = control.client.get('/api/novel-console/reference-adoption/latest', params={
        'workflow_id': 'custom-build', 'workspace': str(fresh)})
    assert response.status_code == 200, response.text
    assert response.json() == {'job': None}
    assert not fresh.exists()
