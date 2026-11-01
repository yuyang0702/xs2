"""Library reads separate the source narrative from transferable target views."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web import novel_routes


@pytest.mark.parametrize('available', [False, True])
def test_unavailable_metadata_capability_returns_plugin_unavailable(tmp_path, monkeypatch, available):
    from types import SimpleNamespace
    def service():
        if not available:
            raise ValueError('小说插件未启用')
        return SimpleNamespace()
    monkeypatch.setattr(novel_routes, 'console_service', service)
    monkeypatch.setattr(novel_routes, '_library_root', tmp_path)
    folder = tmp_path / 'example'
    folder.mkdir()
    (folder / 'manifest.json').write_text('{"id": "example"}', encoding='utf-8')
    app = FastAPI()
    app.include_router(novel_routes.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ('/api/novel-console/library', '/api/novel-console/library/example'):
            response = client.get(path)
            assert response.status_code == 503
            assert '插件' in response.json()['detail']


def test_list_and_detail_derive_viewpoints_without_rewriting_saved_metadata(tmp_path, monkeypatch):
    service_path = Path(__file__).resolve().parents[2] / 'DeterminFlow-Plugins/plugins/xs2-novel-flywheel/resources/script-library/xs2/console_service/console_service.py'
    if not service_path.is_file():
        pytest.skip('novel plugin checkout is not available for integration testing')
    spec = importlib.util.spec_from_file_location('library_metadata_route_service', service_path,
                                               submodule_search_locations=[str(service_path.parent)])
    service = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = service
    spec.loader.exec_module(service)
    monkeypatch.setattr(novel_routes, 'console_service', lambda: service)
    monkeypatch.setattr(novel_routes, '_library_root', tmp_path)
    folder = tmp_path / 'example'
    folder.mkdir()
    files = {
        'manifest.json': {'id': 'example', 'name': 'Library', 'pov': ['third_person']},
        'profile.json': {'markdown': 'Source analysis'},
        'candidates.json': {'candidates': [{'candidate_id': 'one', 'source_pov': ['first_person'],
                                         'target_pov': ['first_person', 'third_person']}]},
    }
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value), encoding='utf-8')
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    app = FastAPI()
    app.include_router(novel_routes.router)
    with TestClient(app) as client:
        listed = client.get('/api/novel-console/library').json()['items'][0]
        detailed = client.get('/api/novel-console/library/example').json()['manifest']
    expected = {'source_pov': ['first_person'], 'source_status': 'known', 'source_basis': 'candidates',
                'target_pov': ['first_person', 'third_person'], 'target_status': 'known'}
    assert listed.get('pov_metadata') == expected
    assert detailed.get('pov_metadata') == expected
    assert listed['pov'] == detailed['pov'] == ['third_person']
    assert before == {path.name: path.read_bytes() for path in folder.iterdir()}
