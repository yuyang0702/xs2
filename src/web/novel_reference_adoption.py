"""Host adapters; the enabled plugin owns reference matching and adoption."""
import json
from pathlib import Path
import subprocess
import sys

from src.core.llm_client import create_llm
from src.workflow.script_library import get_script_library
from .novel_plugin import console_service, OWNER
from .novel_library import enrich_candidates
from .novel_reference_choices import with_reference_choices


def reference_catalog():
    from . import novel_routes
    root = novel_routes._library_root.resolve()
    result = []
    for folder in sorted(root.iterdir()) if root.is_dir() else ():
        if not folder.is_dir() or folder.is_symlink() or folder.name.startswith('.'):
            continue
        manifest_path, candidates_path = folder / 'manifest.json', folder / 'candidates.json'
        if not manifest_path.is_file() or not candidates_path.is_file():
            continue
        for file in (manifest_path, candidates_path, folder / 'profile.json'):
            if file.is_symlink() or not file.resolve().is_relative_to(root):
                raise ValueError('写法库包含不安全的链接，请先检查来源')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if manifest.get('id') != folder.name:
            raise ValueError('写法库编号与来源目录不一致，请刷新写法库')
        data = with_reference_choices(json.loads(candidates_path.read_text(encoding='utf-8-sig')))
        profile = folder / 'profile.json'
        result.append({'library_id': folder.name, 'name': manifest.get('name', folder.name),
                       'candidates': data, 'manifest': manifest,
                       'profile': json.loads(profile.read_text(encoding='utf-8-sig')) if profile.is_file() else {}})
    return result


def reference_runner(root: Path, selection: dict):
    catalog = get_script_library()
    identity = next((item for item in catalog.list_scripts()
                     if item['owner'] == OWNER and item['name'] == 'reference_distill'), None)
    location = catalog.resolve_file(identity['group'], identity['name'], 'reference_distill.py') if identity else None
    if location is None:
        raise ValueError('小说插件缺少采用参考写法能力，请更新插件后重试')
    result = subprocess.run([sys.executable, str(location.directory / 'reference_distill.py'),
                             'adopt', '--selection-json', json.dumps(selection, ensure_ascii=False)],
                            cwd=str(root), capture_output=True, encoding='utf-8', errors='replace', timeout=120)
    if result.returncode:
        raise ValueError('写法未生效：' + (result.stderr or result.stdout or '插件采用失败')[-2000:])
    return result.stdout


class ReferenceAdoptionJobs:
    def __init__(self, guard):
        self.guard = guard
        self._delegate = None

    @property
    def delegate(self):
        from .novel_routes import _lock
        service = console_service()
        capability = getattr(service, 'ReferenceAdoptionJobs', None)
        if capability is None:
            raise ValueError('小说插件尚未提供兼容检查与快速采用，请更新并重启')
        if self._delegate is None:
            self._delegate = capability(
                model_factory=lambda **kwargs: create_llm(**kwargs),
                catalog_loader=reference_catalog,
                candidate_merger=lambda old, new: enrich_candidates(old, new, exact_ids=True),
                reference_runner=reference_runner, lock=_lock, guard=self.guard)
        return self._delegate

    def start(self, root, request_id, payload):
        return self.delegate.start(root, request_id, payload)

    def get(self, root, request_id):
        return self.delegate.get(root, request_id)

    def latest(self, root):
        return self.delegate.latest(root)

    def has_active(self, root):
        if self._delegate is None:
            return False
        return self._delegate.has_active(root)

    async def stop(self):
        if self._delegate is not None:
            await self._delegate.stop()
