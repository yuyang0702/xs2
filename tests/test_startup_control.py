"""Safe duplicate-launch control: no models and no live service processes."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse


def _module():
    try:
        return importlib.import_module("src.startup_control")
    except ModuleNotFoundError as exc:
        assert exc.name != "src.startup_control", "safe startup control has not been implemented"
        raise


class Job:
    def __init__(self, done=False):
        self.finished = done

    def done(self):
        return self.finished


def _app(tmp_path, monkeypatch):
    control = _module()
    monkeypatch.setattr(control, "WORKFLOWS_DIR", tmp_path / "workflows")
    app = FastAPI()
    app.state.session_manager = SimpleNamespace(sessions={})
    app.state.workflow_manager = SimpleNamespace(_running_tasks={})
    app.state.roundtable_manager = None
    app.state.workflow_executor_pool = None
    app.state.novel_automation = None
    app.state.stopped = 0
    app.post("/mutation")(lambda: {"ok": True})
    app.mount("/", PlainTextResponse("static"))
    guard = tmp_path / "logs" / "launch.guard"
    monkeypatch.setenv("DETERMINFLOW_LAUNCH_GUARD_FILE", str(guard))
    control.install_control(app, root=tmp_path, profile_id="profile", token="launch-token",
                            secret="private-control-secret", guard_file=guard,
                            shutdown=lambda: setattr(app.state, "stopped", app.state.stopped + 1))
    return control, app, guard


async def _request(app, method="GET", path="/api/startup-control", *, headers=None, body=None, host="127.0.0.1"):
    transport = httpx.ASGITransport(app=app, client=(host, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        return await client.request(method, path, headers=headers or {"X-DeterminFlow-Control": "private-control-secret"}, json=body)


def _restart(app, **kwargs):
    return _request(app, "POST", "/api/startup-restart", body={"token": "launch-token", "profile_id": "profile"}, **kwargs)


def test_idle_running_main_allows_restart_without_persisting_data(tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    app.state.session_manager.sessions["main"] = SimpleNamespace(status="running", invocation_active=False)
    response = asyncio.run(_request(app))
    assert response.status_code == 200
    assert response.json() == {"protocol": 1, "project_root": str(tmp_path.resolve()), "profile_id": "profile",
                               "token": "launch-token", "pid": os.getpid(), "busy": False, "reasons": [], "can_restart": True}
    assert "private-control-secret" not in response.text
    response = asyncio.run(_restart(app))
    assert response.status_code == 202
    assert app.state.stopped == 1
    assert guard.is_file()
    assert list(tmp_path.rglob("*")) == [tmp_path / "logs", guard]


@pytest.mark.parametrize("kind", ["chat", "workflow", "assistant", "adoption", "roundtable"])
def test_live_work_preserves_server_and_restores_admission(kind, tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    if kind == "chat":
        app.state.session_manager.sessions["sub"] = SimpleNamespace(invocation_active=True)
    elif kind == "workflow":
        app.state.workflow_manager._running_tasks["task"] = Job()
    elif kind == "roundtable":
        app.state.roundtable_manager = SimpleNamespace(_tasks={"meeting": Job()}, sessions={})
    else:
        key = "novel_assistant_jobs" if kind == "assistant" else "novel_reference_adoption_jobs"
        setattr(app.state, key, SimpleNamespace(_delegate=SimpleNamespace(tasks={"job": Job()})))
    activity = asyncio.run(control.collect_activity(app))
    assert activity.busy and activity.reasons
    response = asyncio.run(_restart(app))
    assert response.status_code == 409
    assert response.json()["status"] == "busy"
    assert app.state.stopped == 0
    assert not guard.exists()
    assert asyncio.run(_request(app, "POST", "/mutation")).status_code == 200


@pytest.mark.parametrize("status", ["running", "preparing", "retry_waiting", "resume_pending", "corrupt"])
def test_persisted_active_or_unreadable_tasks_fail_closed(status, tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    path = tmp_path / "workflows" / "wf" / "tasks" / "t.json"
    path.parent.mkdir(parents=True)
    path.write_text("{" if status == "corrupt" else json.dumps({"status": status}), encoding="utf-8")
    before = path.read_bytes()
    response = asyncio.run(_restart(app))
    assert response.status_code == 409
    assert path.read_bytes() == before
    assert not guard.exists()


def test_historical_pre_running_and_uninitialized_job_delegates_are_idle(tmp_path, monkeypatch):
    _, app, _ = _app(tmp_path, monkeypatch)
    path = tmp_path / "workflows" / "wf" / "tasks" / "t.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "pre_running"}), encoding="utf-8")
    class LazyJobs:
        _delegate = None
        @property
        def tasks(self):
            raise AssertionError("inspection must not instantiate the lazy plugin delegate")
    app.state.novel_assistant_jobs = LazyJobs()
    assert asyncio.run(_request(app)).json()["can_restart"] is True


def test_armed_automation_between_steps_is_busy_and_unchanged(tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    novel = tmp_path / "book"
    novel.mkdir()
    path = novel / ".novel-project.json"
    original = json.dumps({"autoNext": True, "autoController": "server-v1", "autoArmed": True})
    path.write_text(original, encoding="utf-8")
    app.state.novel_automation = SimpleNamespace(roots=lambda: [novel])
    assert asyncio.run(_restart(app)).status_code == 409
    assert path.read_text(encoding="utf-8") == original
    assert not guard.exists()


@pytest.mark.parametrize("override", [{"available": False}, {"reachable": False}, {"is_ready": False}, {"active_task_count": 1}, {"active_task_count": None}])
def test_remote_unknown_or_busy_prevents_restart(override, tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    app.state.workflow_executor_pool = object()
    member = {"reachable": True, "is_ready": True, "active_task_count": 0, **override}
    async def status(*args, **kwargs):
        return {"mode": "process", "available": override.get("available", True), "degraded": False,
                "configured_count": 1, "members": [member]}
    monkeypatch.setattr(control, "collect_workflow_executor_status", status)
    assert asyncio.run(_restart(app)).status_code == 409
    assert not guard.exists()


@pytest.mark.parametrize("headers,host", [({}, "127.0.0.1"), ({"X-DeterminFlow-Control": "wrong"}, "127.0.0.1"),
    ({"X-DeterminFlow-Control": "private-control-secret", "Origin": "http://localhost"}, "127.0.0.1"),
    ({"X-DeterminFlow-Control": "private-control-secret", "Sec-Fetch-Site": "same-origin"}, "127.0.0.1"),
    ({"X-DeterminFlow-Control": "private-control-secret"}, "192.168.1.20")])
def test_control_requires_non_browser_loopback_secret(headers, host, tmp_path, monkeypatch):
    _, app, _ = _app(tmp_path, monkeypatch)
    async def check():
        transport = httpx.ASGITransport(app=app, client=(host, 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.get("/api/startup-control", headers=headers)
    assert asyncio.run(check()).status_code == 403


@pytest.mark.parametrize("body", [{"token": "wrong", "profile_id": "profile"}, {"token": "launch-token", "profile_id": "wrong"}, {}])
def test_restart_identity_must_match(body, tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    response = asyncio.run(_request(app, "POST", "/api/startup-restart", body=body))
    assert response.status_code == 403
    assert not guard.exists()


def test_post_rechecks_after_get_and_two_posts_never_shutdown_twice(tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    assert asyncio.run(_request(app)).json()["can_restart"]
    app.state.session_manager.sessions["late"] = SimpleNamespace(invocation_active=True)
    assert asyncio.run(_restart(app)).status_code == 409
    app.state.session_manager.sessions.clear()
    async def concurrent():
        return await asyncio.gather(_restart(app), _restart(app))
    responses = asyncio.run(concurrent())
    assert sorted(response.status_code for response in responses) == [202, 409]
    assert app.state.stopped == 1 and guard.exists()


def test_admission_closed_during_await_and_final_local_check_catches_race(tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    async def delayed(app):
        assert guard.exists()
        from src.runtime_admission import ensure_accepting
        with pytest.raises(RuntimeError, match="重启"):
            ensure_accepting()
        assert (await _request(app, "POST", "/mutation")).status_code == 503
        app.state.session_manager.sessions["race"] = SimpleNamespace(invocation_active=True)
        await asyncio.sleep(0)
        return control.Activity([])
    monkeypatch.setattr(control, "collect_activity", delayed)
    assert asyncio.run(_restart(app)).status_code == 409
    assert not guard.exists() and app.state.stopped == 0


def test_failed_collection_restores_only_owned_marker(tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    async def broken(app):
        raise OSError("private-state-path")
    monkeypatch.setattr(control, "collect_activity", broken)
    response = asyncio.run(_restart(app))
    assert response.status_code == 409 and "private-state-path" not in response.text
    assert not guard.exists()
    guard.write_text("another-owner", encoding="utf-8")
    assert asyncio.run(_restart(app)).status_code == 409
    assert guard.read_text(encoding="utf-8") == "another-owner"


def test_session_and_novel_entrypoints_obey_ephemeral_guard(tmp_path, monkeypatch):
    _, _, guard = _app(tmp_path, monkeypatch)
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("closed", encoding="utf-8")
    from src.web.novel_assistant import NovelAssistantJobs
    from src.web.novel_reference_adoption import ReferenceAdoptionJobs
    from src.web.novel_automation import NovelAutomation
    from src.agent.session import AgentSession
    for jobs in [NovelAssistantJobs(), ReferenceAdoptionJobs(lambda root: None)]:
        with pytest.raises(RuntimeError, match="重启"):
            jobs.start(tmp_path, "request", {})
        assert jobs._delegate is None
    automation = NovelAutomation(None, None, None, None, None, None, tmp_path)
    assert automation._next_dispatch(tmp_path) is None
    session = object.__new__(AgentSession)
    session._invoke_lock = asyncio.Lock()
    session._termination_requested = False
    async def invoke():
        async with session._invocation_scope():
            pytest.fail("guard must reject before session checkpoint mutations")
    with pytest.raises(RuntimeError, match="重启"):
        asyncio.run(invoke())


def test_workflow_guard_blocks_create_and_resume_without_persistent_control(tmp_path, monkeypatch):
    _, _, guard = _app(tmp_path, monkeypatch)
    from src.workflow.manager import WorkflowManager
    manager = object.__new__(WorkflowManager)
    manager._execution_control = SimpleNamespace(read=lambda: pytest.fail("launch guard should avoid persisted control"))
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("closed", encoding="utf-8")
    assert manager._new_task_admission_result()["error"] == "runtime_draining"
    assert asyncio.run(manager.run_task("wf", "task"))["error"] == "runtime_draining"
    assert asyncio.run(manager.start_pre_running_task("wf", "task"))["error"] == "runtime_draining"


def test_actual_background_activity_is_busy_and_closed_entrypoints_do_no_work(tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    from src import runtime_admission
    assert hasattr(runtime_admission, "activity_scope"), "background work needs atomic tracked admission"
    with runtime_admission.activity_scope("后台测试任务正在进行。"):
        assert asyncio.run(control.collect_activity(app)).busy
        assert asyncio.run(_restart(app)).status_code == 409
    assert not asyncio.run(control.collect_activity(app)).busy
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("closed", encoding="utf-8")
    from src.cron.scheduler import CronScheduler
    from src.memory.jobs import MemoryJobMixin
    from src.roundtable.runner import RoundtableManager
    from src.web.novel_automation import NovelAutomation
    # Uninitialized objects make any touching of job stores, timestamps or files fail.
    assert asyncio.run(object.__new__(CronScheduler)._tick()) is None
    assert asyncio.run(object.__new__(MemoryJobMixin).process_due_jobs()) == 0
    assert asyncio.run(object.__new__(RoundtableManager).start("rt"))["success"] is False
    assert asyncio.run(object.__new__(RoundtableManager).resume("rt"))["success"] is False
    assert asyncio.run(object.__new__(NovelAutomation).tick(tmp_path)) is None


def test_initialized_broken_job_metadata_is_unknown(tmp_path, monkeypatch):
    _, app, _ = _app(tmp_path, monkeypatch)
    app.state.novel_assistant_jobs = SimpleNamespace(_delegate=object())
    assert asyncio.run(_request(app)).json()["can_restart"] is False


def test_inflight_mutation_prevents_restart(tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        async def route():
            entered.set()
            await release.wait()
            return {"ok": True}
        # Insert before the static catchall and before middleware construction.
        router = FastAPI()
        router.post("/saving")(route)
        app.router.routes[0:0] = router.router.routes[4:]
        saving = asyncio.create_task(_request(app, "POST", "/saving"))
        await entered.wait()
        response = await _restart(app)
        release.set()
        assert (await saving).status_code == 200
        return response
    assert asyncio.run(check()).status_code == 409
    assert not guard.exists()


def test_guard_rejects_new_websocket_without_entering_handler(tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("closed", encoding="utf-8")
    async def check():
        events = []
        async def receive():
            pytest.fail("closed websocket must not enter its handler")
        async def send(event):
            events.append(event)
        await app({"type": "websocket", "path": "/ws", "headers": [], "client": ("127.0.0.1", 123)}, receive, send)
        return events
    assert asyncio.run(check()) == [{"type": "websocket.close", "code": 1013}]


def test_detached_session_guard_rejects_before_rehydration(tmp_path, monkeypatch):
    _, _, guard = _app(tmp_path, monkeypatch)
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("closed", encoding="utf-8")
    from src.agent.extension_sessions import ExtensionSessionRuntime
    detached = object.__new__(ExtensionSessionRuntime)
    with pytest.raises(RuntimeError, match="重启"):
        asyncio.run(detached.invoke("session", "hello"))
    with pytest.raises(RuntimeError, match="重启"):
        asyncio.run(detached.resume_tools("session", {}))


def test_sync_novel_start_is_tracked_while_registering_task(tmp_path, monkeypatch):
    control, app, _ = _app(tmp_path, monkeypatch)
    from src.web.novel_assistant import NovelAssistantJobs
    jobs = NovelAssistantJobs()
    def start(*args):
        assert control._local_activity(app).busy, "registration preparation must fence restart before its task exists"
        return {"id": "new"}
    jobs._delegate = SimpleNamespace(start=start)
    # Bypass only plugin discovery; exercise the real facade's task admission.
    monkeypatch.setattr(NovelAssistantJobs, "delegate", property(lambda self: self._delegate))
    assert jobs.start(tmp_path, "request", {}) == {"id": "new"}


def test_healthy_idle_remote_pool_allows_restart(tmp_path, monkeypatch):
    control, app, _ = _app(tmp_path, monkeypatch)
    app.state.workflow_executor_pool = object()
    async def status(*args, **kwargs):
        return {"mode": "process", "available": True, "degraded": False, "configured_count": 1,
                "members": [{"reachable": True, "is_ready": True, "active_task_count": 0}]}
    monkeypatch.setattr(control, "collect_workflow_executor_status", status)
    assert asyncio.run(_restart(app)).status_code == 202


def test_remote_collection_error_is_unknown_and_restores_service(tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    async def status(*args, **kwargs):
        raise TimeoutError("executor internal endpoint")
    monkeypatch.setattr(control, "collect_workflow_executor_status", status)
    result = asyncio.run(_restart(app))
    assert result.status_code == 409 and "executor internal endpoint" not in result.text
    assert not guard.exists()


def test_corrupt_automation_metadata_preserves_server(tmp_path, monkeypatch):
    _, app, _ = _app(tmp_path, monkeypatch)
    path = tmp_path / ".novel-project.json"
    path.write_text("{", encoding="utf-8")
    app.state.novel_automation = SimpleNamespace(roots=lambda: [tmp_path])
    assert asyncio.run(_restart(app)).status_code == 409
    assert path.read_text(encoding="utf-8") == "{"


def test_cancelled_restart_reopens_admission(tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    async def check():
        entered = asyncio.Event()
        async def blocked(app):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(control, "collect_activity", blocked)
        request = asyncio.create_task(_restart(app))
        await entered.wait()
        assert guard.exists()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
    asyncio.run(check())
    assert not guard.exists() and app.state.stopped == 0


@pytest.mark.parametrize("count", [None, "0", -1, True])
def test_real_executor_sanitizer_preserves_unknown_activity(count, tmp_path, monkeypatch):
    _, app, guard = _app(tmp_path, monkeypatch)
    import src.config as config
    monkeypatch.setattr(config, "WORKFLOW_EXECUTOR_MODE", "process")
    class Pool:
        executor_count = 1
        def status_snapshot(self):
            member = {"executor_id": "e", "epoch": "epoch", "pid": 7, "status": "ready", "is_ready": True,
                      "reachable": True, "active_task_count": count}
            return {"mode": "process", "available": True, "configured_count": 1, "members": [member]}
    app.state.workflow_executor_pool = Pool()
    assert asyncio.run(_restart(app)).status_code == 409
    assert not guard.exists()


def test_busy_chat_keeps_existing_websocket_and_never_closes_admission(tmp_path, monkeypatch):
    control, app, guard = _app(tmp_path, monkeypatch)
    assert asyncio.run(_request(app)).json()["can_restart"]
    app.state.session_manager.sessions["late"] = SimpleNamespace(invocation_active=True)
    monkeypatch.setattr(control, "create_guard", lambda *args: pytest.fail("known busy chat must keep admission open"))
    assert asyncio.run(_restart(app)).status_code == 409
    assert app.state.session_manager.sessions["late"].invocation_active is True
    assert not guard.exists()
    async def check_existing():
        received = []
        async def receive():
            guard.parent.mkdir(parents=True, exist_ok=True)
            guard.write_text("provisional", encoding="utf-8")
            return {"type": "websocket.receive", "text": "current chat"}
        async def handler(scope, recv, send):
            received.append(await recv())
        async def send(event):
            pytest.fail("existing websocket must remain connected while checking")
        middleware = control.AdmissionMiddleware(handler, app.state.startup_control)
        await middleware({"type": "websocket", "path": "/ws"}, receive, send)
        return received
    assert asyncio.run(check_existing()) == [{"type": "websocket.receive", "text": "current chat"}]
