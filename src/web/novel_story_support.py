"""Use the enabled novel plugin's shared implementation, not a second engine."""
import importlib.util
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def _load(path: str, modified: int):
    spec = importlib.util.spec_from_file_location('xs2_novel_story_support', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def story_support(required=False):
    from src.workflow.script_library import get_script_library
    catalog = get_script_library()
    # Installation namespaces may differ from the default prefix. Select the
    # enabled owner's actual resource identity instead of assuming a local ID.
    identity = next((item for item in catalog.list_scripts()
                     if item['owner'] == 'xs2-novel-flywheel' and item['name'] == 'story_support'), None)
    location = catalog.resolve_file(identity['group'], 'story_support', 'story_support.py') if identity else None
    if not location:
        if required:
            raise ValueError('剧情支持模块尚未加载，请更新小说工作流并重启程序。')
        return None
    path = location.directory / 'story_support.py'
    return _load(str(path), path.stat().st_mtime_ns)
