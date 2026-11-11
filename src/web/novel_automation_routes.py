"""Explicit start/stop and read-only progress for plugin-owned production."""
from fastapi import APIRouter, HTTPException, Request
from pathlib import Path

from src.core.workspace_manager import resolve_workflow_workspace_path

from .novel_routes import ProjectSave, _lock, _manifest, atomic_json, read_json_file, register_project
from .workflow_access import _ensure_http_mutation_allowed, _ensure_workflow_writable, _get_manager
from .novel_plugin import workflow_resources, console_service

router = APIRouter(prefix="/api/novel-console/automation", tags=["novel-console"])


def _root(request, workflow_id, workspace, *, allow_missing=False):
    from src import config
    if not workspace.strip():
        raise HTTPException(400, "工作区路径不能为空")
    manager = _get_manager(request)
    try:
        candidate = Path(workspace).expanduser()
        intended = (candidate if candidate.is_absolute() else config.BASE_DIR / candidate).resolve()
        resolved = resolve_workflow_workspace_path(workflow_id, workspace, base_dir=manager._ws_manager.base_dir)
        if intended != resolved or ".." in candidate.parts:
            raise ValueError("工作区路径不在允许范围内")
        if intended.exists() and not intended.is_dir():
            raise HTTPException(400, "工作区路径不是目录")
        if not allow_missing and not intended.is_dir():
            raise HTTPException(404, "工作区不存在")
        # Validation uses the non-mutating resolver: rejected paths never create
        # or touch the default workflow workspace as a fallback.
        return intended
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("")
def status(request: Request, workflow_id: str, workspace: str):
    with _lock:
        return {"state": read_json_file(_root(request, workflow_id, workspace) / _manifest, {})}


@router.post("/start")
def start(payload: ProjectSave, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    manager = _ensure_workflow_writable(request, payload.workflow_id)
    service = getattr(request.app.state, "novel_automation", None)
    if service is None:
        raise HTTPException(503, "后台创作服务尚未就绪")
    try:
        resources = workflow_resources(request.app.state.extension_manager, manager)
        console_service()
    except ValueError as error:
        raise HTTPException(503, str(error)) from error
    if payload.workflow_id not in resources.values():
        raise HTTPException(400, "当前工作流不属于小说插件")
    root = _root(request, payload.workflow_id, payload.workspace, allow_missing=True)
    with _lock:
        adoption = getattr(request.app.state, "novel_reference_adoption_jobs", None)
        if adoption and adoption.has_active(root):
            raise HTTPException(409, "正在检查并采用本书写法，请等待完成后启动自动创作")
        manifest = root / _manifest
        new_project = not manifest.is_file()
        existing = read_json_file(manifest, {})
        revision = existing.get("_revision", 0)
        if service.has_active(root) or payload.state.get("_revision", 0) != revision:
            raise HTTPException(409, "作品已在后台更新，请刷新后操作")
        incoming = dict(payload.state)
        if incoming.get("stageId") not in console_service().production.STAGES:
            raise HTTPException(400, "请先完成参考准备及方向确认，再启动自动创作")
        incoming.update(autoNext=True, autoController="server-v1", autoArmed=True,
                        autoPauseReason="", _revision=revision + 1, persisted=True)
        incoming["automaticRecovery"] = existing.get("automaticRecovery", {})
        incoming['automaticCheckpoint'] = existing.get('automaticCheckpoint')
        pending = existing.get("autoPending")
        if pending and pending.get("task_id") and pending.get("workflow_id"):
            try:
                prior_task = manager.get_task(pending["workflow_id"], pending["task_id"])
            except FileNotFoundError:
                prior_task = None
            changed_scope = (incoming.get('stageId') != existing.get('stageId') or
                             incoming.get('values', {}).get('chapter_number') != existing.get('values', {}).get('chapter_number'))
            fresh_attempt = (existing.get('refs', {}).get(existing.get('stageId')) and
                             incoming.get('refs', {}).get(existing.get('stageId')) != existing['refs'][existing['stageId']])
            if prior_task and (prior_task.get("status") == "completed" or
                               (prior_task.get('status') == 'stopped' and (changed_scope or fresh_attempt))):
                workspace = prior_task.get("workspace_override")
                if workspace and Path(workspace).resolve() != root:
                    raise HTTPException(409, "待恢复任务不属于本书，请检查任务归属")
                pending = None
        if pending:
            if (incoming.get("stageId") != existing.get("stageId") or
                    incoming.get("values", {}).get("chapter_number") != existing.get("values", {}).get("chapter_number")):
                raise HTTPException(409, "当前步骤仍有待恢复任务，请先恢复该步骤")
            incoming["autoPending"] = pending
            incoming["refs"] = existing.get("refs", {})
        else:
            incoming.pop("autoPending", None)
        atomic_json(manifest, incoming)
        register_project(root, new_project=new_project)
    return {"state": incoming, "workspace": str(root), "revision": incoming["_revision"]}


@router.post("/stop")
def stop(payload: ProjectSave, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    service = getattr(request.app.state, "novel_automation", None)
    if service is None:
        raise HTTPException(503, "后台创作服务尚未就绪")
    root = _root(request, payload.workflow_id, payload.workspace)
    return {"state": service.pause(root)}
