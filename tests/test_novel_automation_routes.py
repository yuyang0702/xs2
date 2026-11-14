"""HTTP state transitions use the durable controller without a live app or models."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.workspace_manager import WorkspaceManager
from src.extension_host.resource_ids import ResourceIdResolver, build_resource_id_plan
from src.web.novel_automation import NovelAutomation
from src.web import novel_routes, novel_automation_routes


class RecordingManager:
    def __init__(self, base):
        self._ws_manager = WorkspaceManager(str(base / "data/workspaces"))
        self.directory = base / "data/workflows"
        self.enabled = True
        self.execution_policy = "public"
        self.created = []
        self.started = []

    def is_workflow_owner_enabled(self, workflow_id):
        return self.enabled

    def get_workflow_execution_policy(self, workflow_id):
        return self.execution_policy

    def list_workflows(self):
        return {"workflows": [{"workflow_id": "renamed-build"}]}

    def get_workflow(self, workflow_id):
        return {"definition": {"workflow_id": workflow_id, "nodes": [], "variables": []}}

    def create_task(self, workflow_id, **kwargs):
        task = {"workflow_id": workflow_id, "task_id": "pending-1", "status": "pending", **kwargs}
        self.created.append(task)
        self.save(task)
        return task

    def save(self, task):
        path = self.directory / task["workflow_id"] / "tasks" / (task["task_id"] + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(task), encoding="utf-8")

    def get_task(self, workflow_id, task_id):
        return json.loads((self.directory / workflow_id / "tasks" / (task_id + ".json")).read_text())

    async def run_task(self, workflow_id, task_id):
        task = self.get_task(workflow_id, task_id)
        task["status"] = "running"
        self.save(task)
        self.started.append(task_id)
        return {"success": True}


@pytest.fixture
def control(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    manager = RecordingManager(tmp_path)
    root = tmp_path / "data/workspaces/books/book with spaces"
    root.mkdir(parents=True)
    state = {"title": "Original", "_revision": 1, "stageId": "build", "autoNext": False,
             "autoScope": "short_full", "values": {"chapter_number": "0001", "premise": "story"},
             "refs": {}, "completed": [], "persisted": True}
    novel_routes.atomic_json(root / ".novel-project.json", state)
    monkeypatch.setattr(novel_routes, "_index", tmp_path / "data/novel-console/workspaces.json")
    resolver = ResourceIdResolver()
    resolver.register(build_resource_id_plan("xs2-novel-flywheel", "renamed", {"workflows": ["build"]}))
    extensions = SimpleNamespace(resource_resolver=resolver, is_running=lambda owner: manager.enabled)
    policy = SimpleNamespace(STAGES=("build",), launch_check=lambda *args: None,
                             parameters=lambda state, definition: {"chapter_number": state["values"]["chapter_number"]},
                             model_overrides=lambda *args: None)
    monkeypatch.setattr(novel_automation_routes, "console_service", lambda: SimpleNamespace(production=policy))
    service = NovelAutomation(manager, lambda: {"build": "renamed-build"}, lambda: [root],
                              lambda: policy, SimpleNamespace(), novel_routes._lock, manager.directory)
    app = FastAPI()
    app.state.workflow_manager = manager
    app.state.extension_manager = extensions
    app.state.novel_automation = service
    app.include_router(novel_routes.router)
    app.include_router(novel_automation_routes.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, root=root, manager=manager, service=service,
                              app=app, original=state, policy=policy)


def payload(control, state=None, **kwargs):
    return {"workflow_id": "renamed-build", "workspace": str(control.root),
            "state": control.original if state is None else state, **kwargs}


def saved(control):
    return json.loads((control.root / ".novel-project.json").read_text(encoding="utf-8"))


def test_start_compares_revision_and_rejects_double_start(control):
    before = saved(control)
    stale = control.client.post("/api/novel-console/automation/start", json=payload(control, {**before, "_revision": 0}))
    assert stale.status_code == 409
    assert saved(control) == before
    response = control.client.post("/api/novel-console/automation/start", json=payload(control))
    assert response.status_code == 200, response.text
    armed = response.json()["state"]
    assert armed["autoArmed"] and armed["autoNext"]
    assert armed["autoController"] == "server-v1"
    assert armed["_revision"] == 2
    duplicate = control.client.post("/api/novel-console/automation/start", json=payload(control, armed))
    assert duplicate.status_code == 409
    assert saved(control) == armed


def test_legacy_save_cannot_arm_and_active_background_state_cannot_be_overwritten(control):
    forged = {**control.original, "autoNext": True, "autoController": "server-v1", "autoArmed": True}
    result = control.client.put("/api/novel-console/projects", json=payload(control, forged))
    assert result.status_code == 200, result.text
    assert saved(control)["autoArmed"] is False
    assert not control.service.has_active(control.root)
    armed = control.client.post("/api/novel-console/automation/start", json=payload(control, saved(control)))
    assert armed.status_code == 200, armed.text
    updated = {**armed.json()["state"], "title": "Stale edit", "autoArmed": False}
    assert control.client.put("/api/novel-console/projects", json=payload(control, updated)).status_code == 409
    assert saved(control)["title"] == "Original"


def test_stop_uses_latest_server_state_even_with_stale_browser_and_disabled_owner(control):
    control.client.post("/api/novel-console/automation/start", json=payload(control))
    latest = saved(control)
    latest.update(title="Background title", refs={"build": {"workflow_id": "renamed-build", "task_id": "retained"}})
    control.service._save(control.root, latest)
    control.manager.enabled = False
    stopped = control.client.post("/api/novel-console/automation/stop", json=payload(control))
    assert stopped.status_code == 200, stopped.text
    result = stopped.json()["state"]
    assert result["title"] == "Background title"
    assert result["refs"] == latest["refs"]
    assert not result["autoArmed"] and not result["autoNext"]
    assert result["_revision"] == latest["_revision"] + 1


def test_paused_pending_task_resumes_after_controller_restart_without_duplicate_creation(control):
    control.client.post("/api/novel-console/automation/start", json=payload(control))
    ref = control.service._next_dispatch(control.root)
    assert ref["task_id"] == "pending-1"
    assert control.manager.started == []
    control.client.post("/api/novel-console/automation/stop", json=payload(control))
    paused = saved(control)
    restarted = NovelAutomation(control.manager, control.service.resources, control.service.roots,
                                 control.service.policy, control.service.assistant_jobs,
                                 novel_routes._lock, control.manager.directory)
    control.app.state.novel_automation = restarted
    wrong_stage = {**paused, "values": {**paused["values"], "chapter_number": "0002"}}
    assert control.client.post("/api/novel-console/automation/start", json=payload(control, wrong_stage)).status_code == 409
    resumed = control.client.post("/api/novel-console/automation/start", json=payload(control, {**paused, "refs": {}}))
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["state"]["refs"]["build"] == ref
    asyncio.run(restarted.tick(control.root))
    asyncio.run(restarted.tick(control.root))
    assert len(control.manager.created) == 1
    assert control.manager.started == ["pending-1"]


def test_completed_dispatch_does_not_replace_new_repair_feedback_or_refs(control):
    control.client.post('/api/novel-console/automation/start', json=payload(control))
    ref = control.service._next_dispatch(control.root)
    task = control.manager.get_task(ref['workflow_id'], ref['task_id'])
    task['status'] = 'completed'
    control.manager.save(task)
    control.client.post('/api/novel-console/automation/stop', json=payload(control))
    paused = saved(control)
    requested = {**paused, 'autoPending':None, 'refs':{},
                 'values':{**paused['values'], 'author_feedback_file':'quality/repairs/new/instructions.md'}}
    response = control.client.post('/api/novel-console/automation/start', json=payload(control, requested))
    assert response.status_code == 200, response.text
    result = response.json()['state']
    assert not result.get('autoPending')
    assert result['refs'] == {}
    assert result['values']['author_feedback_file'] == 'quality/repairs/new/instructions.md'


@pytest.mark.parametrize('status,allowed', [('stopped', True), ('failed', True), ('pending', False), ('running', False)])
@pytest.mark.parametrize('change', ['chapter', 'stage'])
def test_explicit_new_scope_releases_only_a_terminal_old_dispatch(control, status, allowed, change):
    control.client.post('/api/novel-console/automation/start', json=payload(control))
    ref = control.service._next_dispatch(control.root)
    task = control.manager.get_task(ref['workflow_id'], ref['task_id'])
    task['status'] = status
    control.manager.save(task)
    control.client.post('/api/novel-console/automation/stop', json=payload(control))
    paused = saved(control)
    requested = {**paused, 'refs': {}, 'values': {**paused['values'], 'chapter_number': '0002'}}
    if change == 'stage':
        control.policy.STAGES = ('build', 'polish')
        requested.update(stageId='polish', values=paused['values'])
    response = control.client.post('/api/novel-console/automation/start', json=payload(control, requested))
    assert response.status_code == (200 if allowed else 409), response.text
    if allowed:
        assert not response.json()['state'].get('autoPending')
        assert response.json()['state']['refs'] == {}
    else:
        assert saved(control) == paused
    assert control.manager.get_task(ref['workflow_id'], ref['task_id'])['status'] == status


@pytest.mark.parametrize('status,allowed', [('stopped',True),('failed',True),('pending',False),('running',False)])
def test_explicit_fresh_attempt_after_stop_does_not_resurrect_old_dispatch(control,status,allowed):
    control.client.post('/api/novel-console/automation/start',json=payload(control))
    ref=control.service._next_dispatch(control.root)
    task=control.manager.get_task(ref['workflow_id'],ref['task_id']);task['status']=status;control.manager.save(task)
    control.client.post('/api/novel-console/automation/stop',json=payload(control))
    paused=saved(control)
    response=control.client.post('/api/novel-console/automation/start',json=payload(control,{**paused,'refs':{}}))
    assert response.status_code==200,response.text
    result=response.json()['state']
    if allowed:
        assert not result.get('autoPending') and result['refs']=={}
    else:
        assert result['autoPending']==paused['autoPending'] and result['refs']==paused['refs']


@pytest.mark.parametrize('workspace', ['', 'unrelated-book'])
def test_failed_dispatch_cannot_be_retired_without_exact_book_ownership(control,workspace):
    control.client.post('/api/novel-console/automation/start',json=payload(control))
    ref=control.service._next_dispatch(control.root)
    task=control.manager.get_task(ref['workflow_id'],ref['task_id'])
    task.update(status='failed',workspace_override=workspace)
    control.manager.save(task)
    control.client.post('/api/novel-console/automation/stop',json=payload(control))
    paused=saved(control)
    response=control.client.post('/api/novel-console/automation/start',json=payload(control,{**paused,'refs':{}}))
    assert response.status_code==409 and saved(control)==paused


def test_completed_boundary_drops_dispatch_receipt_before_pausing(control):
    data = saved(control)
    data['autoPending'] = {'task_id':'already-completed'}
    control.service._apply_action(control.root, data, {'action':'finish', 'reason':'评估完成'})
    assert 'autoPending' not in saved(control)


@pytest.mark.parametrize("endpoint", ["start", "stop", "status"])
@pytest.mark.parametrize("workspace", ["", "../../outside"])
def test_invalid_workspace_is_rejected_without_fallback_mutation(control, endpoint, workspace):
    before = saved(control)
    if endpoint == "status":
        result = control.client.get("/api/novel-console/automation", params={"workflow_id": "renamed-build", "workspace": workspace})
    else:
        result = control.client.post("/api/novel-console/automation/" + endpoint, json=payload(control, workspace=workspace))
    assert result.status_code == 400, result.text
    assert saved(control) == before
    assert not (control.manager._ws_manager.base_dir / "workflow_renamed-build").exists()


def test_start_requires_enabled_owner_and_public_execution_policy(control):
    before = saved(control)
    control.manager.enabled = False
    assert control.client.post("/api/novel-console/automation/start", json=payload(control)).status_code == 409
    control.manager.enabled = True
    control.manager.execution_policy = "internal_only"
    assert control.client.post("/api/novel-console/automation/start", json=payload(control)).status_code == 403
    assert saved(control) == before


def test_only_valid_start_creates_new_book_after_all_guards_pass(control):
    new_book = control.root.parent / "new book"
    query = {"workflow_id": "renamed-build", "workspace": str(new_book)}
    incoming = {**control.original, "_revision": 0}
    assert control.client.get("/api/novel-console/automation", params=query).status_code == 404
    assert control.client.post("/api/novel-console/automation/stop", json=payload(control, incoming, workspace=str(new_book))).status_code == 404
    invalid_stage = {**incoming, "stageId": "reference-distillation"}
    assert control.client.post("/api/novel-console/automation/start", json=payload(control, invalid_stage, workspace=str(new_book))).status_code == 400
    assert not new_book.exists()
    conflict = {**incoming, "_revision": 3}
    assert control.client.post("/api/novel-console/automation/start", json=payload(control, conflict, workspace=str(new_book))).status_code == 409
    assert not new_book.exists()
    started = control.client.post("/api/novel-console/automation/start", json=payload(control, incoming, workspace=str(new_book)))
    assert started.status_code == 200, started.text
    assert new_book.is_dir()
    assert json.loads((new_book / ".novel-project.json").read_text())["autoArmed"] is True


def test_app_lifespan_advances_tasks_after_browser_stops_making_requests(control):
    service = control.service
    service.resources = lambda: {"build": "renamed-build", "character": "renamed-character"}
    control.policy.STAGES = ("build", "character")
    control.policy.verify_completion = lambda *args: None
    control.policy.next_action = lambda *args: {"action": "advance", "stage": "character"}

    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.workflow_manager = control.manager
    app.state.extension_manager = control.app.state.extension_manager
    app.state.novel_automation = service
    app.include_router(novel_automation_routes.router)

    def wait_for(predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        pytest.fail("Background controller did not advance without browser requests")

    with TestClient(app) as browser:
        response = browser.post("/api/novel-console/automation/start", json=payload(control))
        assert response.status_code == 200, response.text
        # No more HTTP requests: only the controller's lifespan loop can advance.
        wait_for(lambda: len(control.manager.started) == 1)
        first = control.manager.get_task("renamed-build", "pending-1")
        first["status"] = "completed"
        control.manager.save(first)
        wait_for(lambda: len(control.manager.started) == 2)
        assert [task["workflow_id"] for task in control.manager.created] == ["renamed-build", "renamed-character"]
        assert saved(control)["stageId"] == "character"
    assert service._runner is None
