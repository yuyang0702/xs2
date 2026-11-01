"""Thin adapters for capabilities owned by the installed novel plugin."""
from functools import lru_cache
import importlib.util
import hashlib
import sys
import json
from pathlib import Path

from src.workflow.script_library import get_script_library

OWNER = 'xs2-novel-flywheel'


@lru_cache(maxsize=16)
def _load(path: str, signature: str):
    spec = importlib.util.spec_from_file_location('novel_console_' + signature, path, submodule_search_locations=[str(Path(path).parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def console_service():
    catalog = get_script_library()
    identity = next((item for item in catalog.list_scripts()
                     if item['owner'] == OWNER and item['name'] == 'console_service'), None)
    location = catalog.resolve_file(identity['group'], identity['name'], 'console_service.py') if identity else None
    if not location:
        raise ValueError('小说插件的工作台服务尚未加载，请检查插件状态并重新启动。')
    path = location.directory / 'console_service.py'
    signature = hashlib.sha256(b''.join(p.read_bytes() for p in sorted(location.directory.glob('*.py')))).hexdigest()
    return _load(str(path), signature)


def workflow_resources(extension_manager, workflow_manager) -> dict[str, str]:
    if not extension_manager.is_running(OWNER):
        raise ValueError('小说插件未启用或启动失败，请在插件管理中检查。')
    listed = workflow_manager.list_workflows()
    items = listed.get('workflows', []) if isinstance(listed, dict) else listed
    result = {}
    for item in items:
        identity = extension_manager.resource_resolver.mapping_for('workflow', item['workflow_id'])
        if identity and identity.plugin_id == OWNER:
            result[identity.local_id] = identity.effective_id
    return result


def task_files(workflows_dir: Path, stage: str | None = None):
    """Read owner-marked histories, including legacy default-prefix archives."""
    for folder in sorted(workflows_dir.iterdir()) if workflows_dir.exists() else ():
        if not folder.is_dir():
            continue
        if stage is not None:
            marker = folder / '.extension.json'
            ownership = json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else {}
            if ownership.get('owner') != OWNER and not (
                not ownership and folder.name == f'{OWNER}-{stage}'
            ):
                continue
            local = ownership.get('local_id')
            if local != stage and not (local is None and (folder.name == stage or folder.name.endswith('-' + stage))):
                continue
        yield from (folder / 'tasks').glob('*.json')
