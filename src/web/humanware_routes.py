"""HTTP adapter for the enabled novel plugin's character voice capability."""
import importlib.util
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from typing import Literal

from src.config import DATA_DIR
from src.core.workspace_manager import resolve_workflow_workspace_path
from .workflow_access import _get_manager, _ensure_http_mutation_allowed, _ensure_workflow_writable
from .novel_repair import ensure_idle
from .novel_plugin import OWNER, script_service

router = APIRouter(prefix='/api/humanware', tags=['humanware'])


class VoiceRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    workspace: str


class SaveVoiceRequest(VoiceRequest):
    content: str = Field(max_length=500_000)
    expected_revision: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class SaveVoiceCharacterRequest(VoiceRequest):
    character_id: str = Field(min_length=1, max_length=160)
    expected_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    content: str = Field(max_length=500_000)


@lru_cache(maxsize=4)
def _load(path: str, modified: int):
    spec = importlib.util.spec_from_file_location('xs2_voice_support', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _voice_support():
    from src.workflow.script_library import get_script_library
    catalog = get_script_library()
    identity = next((item for item in catalog.list_scripts()
                     if item['owner'] == 'xs2-novel-flywheel' and item['name'] == 'voice_support'), None)
    location = catalog.resolve_file(identity['group'], 'voice_support', 'voice_support.py') if identity else None
    if location is None:
        raise HTTPException(409, '角色声音插件未启用或尚未更新，请启用并更新小说插件。')
    path = location.directory / 'voice_support.py'
    return _load(str(path), path.stat().st_mtime_ns)


def _workspace(request: Request, workflow_id: str, workspace: str, *, mutate=False):
    from src import config
    if mutate:
        _ensure_http_mutation_allowed(request, workflow_id)
        manager = _ensure_workflow_writable(request, workflow_id)
    else:
        manager = _get_manager(request)
    # A rejected override must never silently edit the resolver's fallback.
    if not workspace.strip():
        raise HTTPException(400, '工作区路径不能为空')
    try:
        candidate = Path(workspace).expanduser()
        intended = (candidate if candidate.is_absolute() else config.BASE_DIR / candidate).resolve()
        resolved = resolve_workflow_workspace_path(workflow_id, workspace, base_dir=manager._ws_manager.base_dir)
        if intended != resolved or '..' in candidate.parts:
            raise ValueError('工作区路径不在允许范围内')
        if not intended.is_dir():
            raise HTTPException(404, '工作区不存在')
        return manager._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


def _operate(request: Request, workflow_id: str, workspace: str, operation: str, *args):
    mutations = {'save', 'generate', 'save_character'}
    root = _workspace(request, workflow_id, workspace, mutate=operation in mutations)
    support = _voice_support()
    try:
        if operation in mutations:
            from .novel_routes import require_manual_control
            require_manual_control(request, root)
            ensure_idle(root, DATA_DIR / 'workflows')
        handler = getattr(support, operation, None)
        if not callable(handler):
            raise HTTPException(409, '角色声音插件尚未更新，请更新插件并重新启动。')
        return handler(root, *args)
    except FileExistsError as error:
        raise HTTPException(409, '角色声音文件已存在，请直接编辑；生成模板不会覆盖现有内容。') from error
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from error


@router.get('/status')
async def get_humanware_status(request: Request, workflow_id: str, workspace: str):
    return _operate(request, workflow_id, workspace, 'status')


@router.get('/voice-file')
async def get_voice_file(request: Request, workflow_id: str, workspace: str):
    return _operate(request, workflow_id, workspace, 'read')


@router.post('/voice-file')
async def save_voice_file(payload: SaveVoiceRequest, request: Request):
    args = (payload.content, payload.expected_revision) if payload.expected_revision else (payload.content,)
    return _operate(request, payload.workflow_id, payload.workspace, 'save', *args)


@router.post('/voice-character')
async def save_voice_character(payload: SaveVoiceCharacterRequest, request: Request):
    return _operate(request, payload.workflow_id, payload.workspace, 'save_character',
                    payload.character_id, payload.content, payload.expected_revision)


@router.post('/generate-voice-file')
async def generate_voice_file(payload: VoiceRequest, request: Request):
    return _operate(request, payload.workflow_id, payload.workspace, 'generate')


@router.post('/score-content')
@router.post('/score-chapter')
async def unsupported_scoring():
    raise HTTPException(501, {'error': 'scoring_unsupported',
                             'message': '当前小说插件未提供独立人味评分，请使用模拟读者工作流的真实评估报告。'})


class RevisionRequest(VoiceRequest):
    expected_revision: str = Field(pattern=r'^[a-f0-9]{64}$')


class CharacterPreview(RevisionRequest):
    character_id: str = Field(min_length=1, max_length=160)
    section_id: str | None = Field(default=None, max_length=160)
    source_id: str | None = Field(default=None, max_length=160)
    replacement: str | None = Field(default=None, max_length=12000)
    history_id: str | None = Field(default=None, max_length=64)


class CharacterApply(RevisionRequest):
    preview: dict


class ProsePolicySave(RevisionRequest):
    mode: Literal['inherit', 'narrative_led'] | None = None
    overrides: list[dict] | None = Field(default=None, max_length=100)


class RulePreview(RevisionRequest):
    source_id: str = Field(max_length=200)
    quote: str = Field(max_length=400)
    replacement: str = Field(max_length=400)


def character_workspace(request, workflow_id, workspace, *, mutate=False, history_dir=None):
    manager = _get_manager(request)
    if manager.get_workflow_owner(workflow_id) != OWNER:
        raise HTTPException(400, '此操作需要小说插件所属的工作流。')
    root = _workspace(request, workflow_id, workspace, mutate=mutate)
    from src import config
    candidate = Path(workspace).expanduser()
    candidate = candidate if candidate.is_absolute() else config.BASE_DIR / candidate
    if candidate != root:
        raise HTTPException(400, '请使用作品原始工作区路径。')
    if mutate:
        from .novel_routes import require_manual_control
        require_manual_control(request, root)
        ensure_idle(root, history_dir if history_dir is not None else DATA_DIR / 'workflows')
    return root


def _character_operation(request, workflow_id, workspace, service, operation, *args, mutate=False):
    try:
        root = character_workspace(request, workflow_id, workspace, mutate=mutate)
        return getattr(script_service(service), operation)(root, *args)
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from error


def _operation(request, payload, service, operation, *args, mutate=False):
    return _character_operation(request, payload.workflow_id, payload.workspace, service, operation, *args, mutate=mutate)


@router.get('/characters')
async def get_characters(request: Request, workflow_id: str, workspace: str,
                         chapter: str = Query(default='', max_length=4), q: str = Query(default='', max_length=250)):
    return _character_operation(request, workflow_id, workspace, 'character_center', 'read', chapter, q)


@router.post('/character-preview')
async def preview_character(payload: CharacterPreview, request: Request):
    args = payload.model_dump(exclude={'workflow_id', 'workspace', 'expected_revision'}, exclude_none=True)
    return _operation(request, payload, 'character_center', 'preview', args, payload.expected_revision)


@router.post('/character-apply')
async def apply_character(payload: CharacterApply, request: Request):
    return _operation(request, payload, 'character_center', 'apply',
                      payload.preview, payload.expected_revision, mutate=True)


@router.get('/character-history')
async def get_character_history(request: Request, workflow_id: str, workspace: str,
                                character_id: str | None = Query(default=None, max_length=160)):
    return _character_operation(request, workflow_id, workspace, 'character_center', 'history', character_id)


@router.get('/prose-policy')
async def get_prose_policy(request: Request, workflow_id: str, workspace: str):
    return _character_operation(request, workflow_id, workspace, 'prose_policy', 'read')


@router.post('/prose-policy')
async def save_prose_policy(payload: ProsePolicySave, request: Request):
    args = payload.model_dump(include={'mode', 'overrides'}, exclude_none=True)
    return _operation(request, payload, 'prose_policy', 'save', args, payload.expected_revision, mutate=True)


@router.get('/rule-audit')
async def get_rule_audit(request: Request, workflow_id: str, workspace: str, chapter: str = '0001'):
    return _character_operation(request, workflow_id, workspace, 'prose_policy', 'audit', chapter)


@router.post('/rule-audit')
async def preview_rule_override(payload: RulePreview, request: Request):
    args = payload.model_dump(include={'source_id', 'quote', 'replacement'})
    return _operation(request, payload, 'prose_policy', 'preview_override', args, payload.expected_revision)
