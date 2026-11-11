import asyncio
import json
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web import novel_routes, workflow_routes
from src.workflow import manager, task_queries


def test_project_discovery_reuses_scan_and_sees_new_registration(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    legacy = root / "nested" / "legacy"
    (legacy / "story").mkdir(parents=True)
    index = tmp_path / "index.json"
    monkeypatch.setattr(novel_routes, "WORKFLOW_WORKSPACES_DIR", root)
    monkeypatch.setattr(novel_routes, "_index", index)
    assert novel_routes.known_workspaces() == [legacy.resolve()]

    external = tmp_path / "registered"
    external.mkdir()
    (external / ".novel-project.json").write_text("{}", encoding="utf-8")
    index.write_text(json.dumps([str(external)]), encoding="utf-8")
    def fail_on_rescan(*_args, **_kwargs):
        raise AssertionError("project discovery scanned twice")

    monkeypatch.setattr(novel_routes.os, "walk", fail_on_rescan)
    assert novel_routes.known_workspaces() == sorted([external.resolve(), legacy.resolve()], key=str)


def test_project_scan_leaves_event_loop_and_mutation_lock_free(monkeypatch):
    scanning = threading.Event()
    finish = threading.Event()

    def discover():
        scanning.set()
        assert finish.wait(2)
        return []

    monkeypatch.setattr(novel_routes, "known_workspaces", discover)
    monkeypatch.setattr(novel_routes, "console_service", lambda: None)

    async def check():
        listing = asyncio.create_task(novel_routes.list_projects())
        try:
            assert await asyncio.to_thread(scanning.wait, 1)
            assert not listing.done()
            assert novel_routes._lock.acquire(blocking=False)
            novel_routes._lock.release()
        finally:
            finish.set()
        assert await listing == {"projects": []}

    asyncio.run(check())


def test_task_list_summary_paginates_without_deserializing_node_details(tmp_path, monkeypatch):
    workflow = tmp_path / "example"
    tasks = workflow / "tasks"
    tasks.mkdir(parents=True)
    (workflow / "definition.json").write_text(json.dumps({
        "workflow_id": "example", "name": "Example", "nodes": [],
        "console": {"app": "novel-workbench"},
    }), encoding="utf-8")
    for i in range(3):
        (tasks / f"task-{i}.json").write_text(json.dumps({
            "task_id": f"task-{i}", "workflow_id": "example", "name": f"Example {i}",
            "status": "completed", "created_at": f"2026-11-11T00:00:0{i}",
            "node_states": {"node": {"status": "completed", "outputs": {"body": "large"}}},
        }), encoding="utf-8")
    monkeypatch.setattr(manager, "WORKFLOWS_DIR", tmp_path)
    monkeypatch.setattr(task_queries, "WORKFLOWS_DIR", tmp_path)
    workflow_manager = manager.WorkflowManager.__new__(manager.WorkflowManager)
    workflow_manager._extension_manager = None
    app = FastAPI()
    app.state.workflow_manager = workflow_manager
    app.include_router(workflow_routes.router)
    app.include_router(workflow_routes.tasks_router)
    client = TestClient(app)
    catalog = client.get("/api/workflows?include_task_status=false").json()
    assert catalog[0]["console"] == {"app": "novel-workbench"}
    assert "running_tasks" not in catalog[0]

    def fail_on_full_task(*_args, **_kwargs):
        raise AssertionError("list deserialized a full task")

    monkeypatch.setattr(task_queries.WorkflowTask, "from_dict", fail_on_full_task)
    for route in ("/api/workflows/example/tasks", "/api/tasks"):
        result = client.get(route, params={"summary": "true", "page": 2, "page_size": 1}).json()
        assert result["total"] == 3
        row, = result["tasks"]
        assert row["task_id"] == "task-1"
        assert row["node_count"] == 1
        assert "node_states" not in row and "snapshot_definition" not in row
    (tasks / "task-1.json").unlink()
    assert client.get("/api/tasks?summary=true").json()["total"] == 2
