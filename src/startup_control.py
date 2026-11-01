"""Private loopback control for replacing an idle launch of this project."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hmac
import ipaddress
import json
import os
from pathlib import Path
from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Request
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from src.config import WORKFLOWS_DIR
from src.runtime_admission import GUARD_ENV, RESTART_MESSAGE, active_reasons, create_guard, is_closed
from src.workflow.executor_observability import collect_workflow_executor_status

CONTROL_PATHS = frozenset({"/api/startup-control", "/api/startup-restart"})
ACTIVE_STATUSES = frozenset({"running", "preparing", "retry_waiting", "resume_pending"})
UNKNOWN = "无法确认后台任务状态，请保留当前服务并稍后重试。"


@dataclass
class Activity:
    reasons: list[str]

    @property
    def busy(self) -> bool:
        return bool(self.reasons)


def _unfinished(tasks) -> bool:
    if tasks is None:
        return False
    values = tasks.values() if isinstance(tasks, dict) else tasks
    for task in tuple(values):
        if task is None:
            continue
        done = getattr(task, "done", None)
        if callable(done):
            if not done():
                return True
        else:
            alive = getattr(task, "is_alive", None)
            if not callable(alive) or alive():
                return True
    return False


def _local_activity(app) -> Activity:
    reasons = active_reasons()
    def add(reason):
        if reason not in reasons:
            reasons.append(reason)
    state = app.state
    try:
        manager = state.session_manager
        if manager is None:
            add(UNKNOWN)
        else:
            for session in tuple(manager.sessions.values()):
                if session.invocation_active:
                    add("有对话或智能体调用正在进行。")
            if _unfinished(getattr(manager, "_sub_tasks", None)):
                add("有子会话任务正在进行。")
    except Exception:
        add(UNKNOWN)
    try:
        manager = state.workflow_manager
        if manager is None:
            add(UNKNOWN)
        elif _unfinished(manager._running_tasks):
            add("有工作流任务正在执行。")
        if WORKFLOWS_DIR.exists():
            for workflow in WORKFLOWS_DIR.iterdir():
                tasks = workflow / "tasks"
                if not tasks.exists():
                    continue
                for path in tasks.iterdir():
                    if path.suffix != ".json":
                        continue
                    try:
                        data = json.loads(path.read_text(encoding="utf-8-sig"))
                        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
                            add(UNKNOWN)
                        elif data["status"] in ACTIVE_STATUSES:
                            add("有工作流任务正在执行或等待恢复。")
                    except Exception:
                        add(UNKNOWN)
    except Exception:
        add(UNKNOWN)
    try:
        roundtable = getattr(state, "roundtable_manager", None)
        if roundtable is not None:
            if _unfinished(roundtable._tasks):
                add("有圆桌讨论正在进行。")
            if any(getattr(session, "status", None) == "discussing" for session in tuple(roundtable.sessions.values())):
                add("有圆桌讨论正在进行。")
        for name, reason in (("novel_assistant_jobs", "小说助手正在分析。"),
                             ("novel_reference_adoption_jobs", "参考写法正在检查或采用。")):
            facade = getattr(state, name, None)
            delegate = getattr(facade, "_delegate", None)
            if delegate is not None:
                tasks = delegate.tasks
                if not isinstance(tasks, dict):
                    add(UNKNOWN)
                elif _unfinished(tasks) or _unfinished(getattr(delegate, "_threads", None)):
                    add(reason)
        automation = getattr(state, "novel_automation", None)
        if automation is not None:
            for root in automation.roots():
                path = Path(root) / ".novel-project.json"
                if not path.exists():
                    continue
                project = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(project, dict):
                    add(UNKNOWN)
                elif project.get("autoNext") is True and project.get("autoController") == "server-v1" and project.get("autoArmed") is True:
                    add("后台自动创作仍已启用。")
    except Exception:
        add(UNKNOWN)
    control = getattr(state, "startup_control", None)
    if control is not None and control.active_mutations:
        add("有请求正在保存或启动任务。")
    return Activity(reasons)


async def collect_activity(app) -> Activity:
    """Inspect actual runtime state; unknown or unreadable state remains busy."""
    local = _local_activity(app)
    try:
        pool = app.state.workflow_executor_pool
        status = await asyncio.wait_for(collect_workflow_executor_status(pool, strict_activity=True), timeout=12.0)
        if pool is not None and status.get("mode") != "process":
            local.reasons.append("无法确认远程执行器状态，请保留当前服务。")
        elif status.get("mode") == "process":
            members = status.get("members")
            if (status.get("available") is not True or status.get("degraded") is True
                    or not isinstance(members, list) or not members
                    or len(members) != status.get("configured_count")):
                local.reasons.append("无法确认远程执行器状态，请保留当前服务。")
            else:
                for member in members:
                    count = member.get("active_task_count")
                    if (member.get("reachable") is not True or member.get("is_ready") is not True
                            or not isinstance(count, int) or isinstance(count, bool) or count < 0):
                        local.reasons.append("无法确认远程执行器状态，请保留当前服务。")
                    elif count:
                        local.reasons.append("远程执行器仍有任务正在执行。")
    except Exception:
        local.reasons.append("无法确认远程执行器状态，请保留当前服务。")
    local.reasons = list(dict.fromkeys([*local.reasons, *_local_activity(app).reasons]))
    return local


class AdmissionMiddleware:
    def __init__(self, app, control):
        self.app, self.control = app, control

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        path = scope.get("path", "")
        mutation = kind == "http" and scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and path not in CONTROL_PATHS
        if path not in CONTROL_PATHS and (mutation or kind == "websocket") and is_closed(self.control.guard_file):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1013})
            else:
                await JSONResponse({"error": "runtime_draining", "message": RESTART_MESSAGE}, status_code=503)(scope, receive, send)
            return
        if mutation:
            self.control.active_mutations += 1
        async def guarded_receive():
            if kind == "websocket" and self.control.pending:
                return {"type": "websocket.disconnect", "code": 1013}
            message = await receive()
            if kind == "websocket" and self.control.pending:
                return {"type": "websocket.disconnect", "code": 1013}
            return message
        try:
            await self.app(scope, guarded_receive, send)
        finally:
            if mutation:
                self.control.active_mutations -= 1


class StartupControl:
    def __init__(self, *, app, root, profile_id, token, secret, guard_file, shutdown):
        self.app, self.secret, self.guard_file, self.shutdown = app, secret, guard_file, shutdown
        self.identity = {"protocol": 1, "project_root": str(root.resolve()), "profile_id": profile_id,
                         "token": token, "pid": os.getpid()}
        self.lock = asyncio.Lock()
        self.pending = False
        self.active_mutations = 0

    def authorized(self, request):
        try:
            address = ipaddress.ip_address(request.client.host)
            loopback = address.is_loopback or (getattr(address, "ipv4_mapped", None) is not None and address.ipv4_mapped.is_loopback)
            browser = "origin" in request.headers or any(key.startswith("sec-fetch-") for key in request.headers)
            return loopback and not browser and bool(self.secret) and hmac.compare_digest(
                request.headers.get("x-determinflow-control", ""), self.secret)
        except (ValueError, AttributeError, TypeError):
            return False

    @staticmethod
    def busy(reasons):
        return JSONResponse({"status": "busy", "reasons": list(dict.fromkeys(reasons)) or [UNKNOWN]}, status_code=409)

    async def state(self, request: Request):
        if not self.authorized(request):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        try:
            activity = await collect_activity(self.app)
        except Exception:
            activity = Activity([UNKNOWN])
        if self.pending or is_closed(self.guard_file):
            activity.reasons.append(RESTART_MESSAGE)
        return JSONResponse({**self.identity, "busy": activity.busy, "reasons": activity.reasons, "can_restart": not activity.busy})

    async def restart(self, request: Request):
        if not self.authorized(request):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        try:
            body = await request.json()
            valid = isinstance(body, dict) and body.get("token") == self.identity["token"] and body.get("profile_id") == self.identity["profile_id"]
        except Exception:
            valid = False
        if not valid:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        async with self.lock:
            if self.pending or is_closed(self.guard_file):
                return self.busy([RESTART_MESSAGE])
            local = _local_activity(self.app)
            if local.busy:
                return self.busy(local.reasons)
            owner = uuid4().hex
            owned = False
            try:
                create_guard(self.guard_file, owner)
                owned = True
                activity = await collect_activity(self.app)
                # No awaits between this final snapshot and committing shutdown.
                reasons = [*activity.reasons, *_local_activity(self.app).reasons]
                if reasons:
                    return self.busy(reasons)
                self.pending = True
                return JSONResponse({"status": "restarting", **self.identity}, status_code=202,
                                    background=BackgroundTask(self.shutdown))
            except Exception:
                return self.busy([UNKNOWN])
            finally:
                if owned and not self.pending:
                    try:
                        if self.guard_file.read_text(encoding="utf-8") == owner:
                            self.guard_file.unlink()
                    except OSError:
                        pass


def install_control(app, *, root: Path, profile_id: str, token: str, secret: str,
                    guard_file: Path, shutdown: Callable) -> StartupControl:
    control = StartupControl(app=app, root=Path(root), profile_id=profile_id, token=token, secret=secret,
                             guard_file=Path(guard_file), shutdown=shutdown)
    os.environ[GUARD_ENV] = str(guard_file)
    app.state.startup_control = control
    router = APIRouter()
    router.add_api_route("/api/startup-control", control.state, methods=["GET"], include_in_schema=False)
    router.add_api_route("/api/startup-restart", control.restart, methods=["POST"], include_in_schema=False)
    # StaticFiles '/' must not swallow the private controls.
    app.router.routes[0:0] = router.routes
    app.add_middleware(AdmissionMiddleware, control=control)
    return control
