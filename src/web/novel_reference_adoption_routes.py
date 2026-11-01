"""Guarded HTTP transport for the novel plugin's adoption jobs."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .novel_automation_routes import _root
from .novel_routes import (_lock, _assistant_jobs, _available_assistant_workflow,
                          read_json_file, ensure_idle)
from .novel_plugin import workflow_resources
from .workflow_access import _ensure_http_mutation_allowed, _ensure_workflow_writable, _get_manager
from .novel_reference_adoption import ReferenceAdoptionJobs

router = APIRouter(prefix='/api/novel-console/reference-adoption', tags=['novel-console'])


class AdoptionStart(BaseModel):
    workflow_id: str
    workspace: str
    entry_id: UUID
    request_id: UUID
    expected_revision: int | None = Field(default=None, ge=0)
    model_override: str | None = Field(default=None, max_length=256)


def _available(request, workflow_id):
    manager = _get_manager(request)
    advisor = _available_assistant_workflow(request, manager)
    if workflow_id not in workflow_resources(request.app.state.extension_manager, manager).values():
        raise HTTPException(400, '当前工作流不属于小说插件')
    return manager, advisor


def _guard(request, workflow_id, root):
    from src.config import WORKFLOWS_DIR
    _ensure_workflow_writable(request, workflow_id)
    automation = getattr(request.app.state, 'novel_automation', None)
    if automation and automation.has_active(root):
        raise HTTPException(409, '请先暂停后台自动创作，再采用参考写法')
    ensure_idle(root, WORKFLOWS_DIR)


def _adoption_jobs(request):
    jobs = getattr(request.app.state, 'novel_reference_adoption_jobs', None)
    if jobs is None:
        # Recheck enabled ownership and workspace activity at publication time.
        manager = _get_manager(request)
        resources = workflow_resources(request.app.state.extension_manager, manager)
        build = resources.get('build')
        if not build:
            raise ValueError('小说插件缺少本书工作流')
        jobs = ReferenceAdoptionJobs(lambda root: _guard(request, build, root))
        request.app.state.novel_reference_adoption_jobs = jobs
    return jobs


def _selected_model(manager, advisor):
    from src.core.model_manager import get_model_manager
    from .novel_workflow_models import model_settings, novel_definition
    nodes = model_settings(novel_definition(manager, advisor), get_model_manager())['nodes']
    if len(nodes) != 1 or not nodes[0]['available']:
        raise HTTPException(409, '请先为小说顾问配置可用模型，再检查写法兼容性')
    return nodes[0]['effective_model']


def _request_model(manager, advisor, requested):
    if not requested:
        return _selected_model(manager, advisor)
    from src.core.model_manager import get_model_manager
    if requested not in get_model_manager().get_all_models():
        raise HTTPException(400, '本次检查只能选择已经配置的模型，请刷新模型列表')
    return requested


@router.post('')
async def start(payload: AdoptionStart, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    _ensure_workflow_writable(request, payload.workflow_id)
    manager, advisor = _available(request, payload.workflow_id)
    root = _root(request, payload.workflow_id, payload.workspace)
    try:
        with _lock:
            _guard(request, payload.workflow_id, root)
            project = read_json_file(root / '.novel-project.json', {})
            if payload.expected_revision is not None and payload.expected_revision != project.get('_revision', 0):
                raise HTTPException(409, '作品设置已更新，请刷新后按当前定位检查')
            entry = next((item for item in _assistant_jobs(request).history(root) if item.get('id') == str(payload.entry_id)), None)
            if not entry or entry.get('status') != 'completed' or entry.get('purpose') != 'advisor':
                raise HTTPException(409, '请先完成本书的小说顾问分析，再采用推荐写法')
            if not project:
                base = entry.get('configuration_base', {})
                project = {'mode': base.get('mode', 'short'), 'values': base.get('values', {}),
                           'advisor_brief': base.get('advisor_brief', entry.get('question', ''))}
            job = _adoption_jobs(request).start(root, str(payload.request_id), {
                'entry_id': str(payload.entry_id), 'project': project,
                '_model_override': _request_model(manager, advisor, payload.model_override)})
        return {'job': job}
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from error


@router.get('/latest')
async def latest(request: Request, workflow_id: str, workspace: str):
    _available(request, workflow_id)
    root = _root(request, workflow_id, workspace, allow_missing=True)
    if not root.is_dir():
        return {'job': None}
    try:
        with _lock:
            return {'job': _adoption_jobs(request).latest(root)}
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from error


@router.get('')
async def status(request: Request, workflow_id: str, workspace: str, request_id: UUID):
    _available(request, workflow_id)
    root = _root(request, workflow_id, workspace)
    try:
        with _lock:
            job = _adoption_jobs(request).get(root, str(request_id))
        if not job:
            raise HTTPException(404, '未找到本次写法采用记录')
        return {'job': job}
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from error
