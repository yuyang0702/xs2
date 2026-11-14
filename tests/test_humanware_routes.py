"""Voice adapter uses real workspace and enabled plugin resources, without models."""
from pathlib import Path
from types import SimpleNamespace
import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.workspace_manager import WorkspaceManager
from src.extension_api.registrar import OwnedPath
from src.workflow.script_library import ScriptLibraryCatalog
from src.web import humanware_routes


@pytest.fixture
def voice_client(tmp_path, monkeypatch):
    from src import config
    from src.workflow import script_library
    from src.web import novel_plugin
    monkeypatch.setattr(config, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(humanware_routes, 'DATA_DIR', tmp_path / 'data', raising=False)
    sibling = Path(__file__).resolve().parents[2]
    source = next((sibling / name / 'plugins/xs2-novel-flywheel/resources/script-library'
                   for name in ('plugins', 'DeterminFlow-Plugins')
                   if (sibling / name / 'plugins/xs2-novel-flywheel').is_dir()))
    installed = tmp_path / 'installed'
    shutil.copytree(source / 'xs2/voice_support', installed / 'custom-xs2/voice_support')
    catalog = ScriptLibraryCatalog(tmp_path / 'scripts', [OwnedPath('xs2-novel-flywheel', installed)])
    monkeypatch.setattr(script_library, 'get_script_library', lambda: catalog)
    monkeypatch.setattr(novel_plugin, 'get_script_library', lambda: catalog)
    manager = SimpleNamespace(_ws_manager=WorkspaceManager(str(tmp_path / 'data/workspaces')),
        is_workflow_owner_enabled=lambda _: True, get_workflow_execution_policy=lambda _: 'public',
        get_workflow_owner=lambda _: 'xs2-novel-flywheel')
    app = FastAPI()
    app.state.workflow_manager = manager
    app.include_router(humanware_routes.router)
    book = tmp_path / 'data/workspaces/books/有 空格'
    (book / 'meta').mkdir(parents=True)
    (book / 'meta/character_profiles.md').write_text('# 档案\n\n## 林木\n沉默。\n', encoding='utf-8')
    return TestClient(app), book, manager, catalog


def payload(book, **kwargs):
    return dict(workflow_id='renamed-character', workspace=str(book), **kwargs)


def test_absolute_workspace_round_trip_and_preserves_profiles(voice_client):
    client, book, _, _ = voice_client
    profiles = (book / 'meta/character_profiles.md').read_bytes()
    response = client.get('/api/humanware/status', params=payload(book))
    assert response.status_code == 200, response.text
    assert response.json()['profiles_file_exists']
    result = client.post('/api/humanware/generate-voice-file', json=payload(book))
    assert result.status_code == 200, result.text
    assert result.json()['generation_mode'] == 'template'
    assert '林木' in (book / 'meta/character_voice.md').read_text(encoding='utf-8')
    saved = client.post('/api/humanware/voice-file', json=payload(book, content='# 声音\n\n## 林木\n自定义'))
    assert saved.status_code == 200, saved.text
    read = client.get('/api/humanware/voice-file', params=payload(book))
    assert read.json()['content'] == '# 声音\n\n## 林木\n自定义'
    retry = client.post('/api/humanware/generate-voice-file', json=payload(book))
    assert retry.status_code == 409
    assert (book / 'meta/character_profiles.md').read_bytes() == profiles
    assert client.get('/api/humanware/voice-file', params=payload(book)).json() == read.json()


def test_disabled_owner_and_internal_policy_reject_mutations(voice_client):
    client, book, manager, catalog = voice_client
    manager.is_workflow_owner_enabled = lambda _: False
    assert client.post('/api/humanware/voice-file', json=payload(book, content='x')).status_code == 409
    manager.is_workflow_owner_enabled = lambda _: True
    manager.get_workflow_execution_policy = lambda _: 'internal_only'
    assert client.post('/api/humanware/voice-file', json=payload(book, content='x')).status_code == 403
    manager.get_workflow_execution_policy = lambda _: 'public'
    catalog.owner_enabled = lambda _: False
    assert client.post('/api/humanware/voice-file', json=payload(book, content='x')).status_code == 409
    assert not (book / 'meta/character_voice.md').exists()


def test_invalid_workspace_never_silently_falls_back(voice_client):
    client, book, _, _ = voice_client
    for workspace in ['../../outside', str(book.anchor), '']:
        result = client.post('/api/humanware/voice-file', json=payload(workspace, content='x'))
        assert result.status_code == 400, result.text
    assert not (book / 'meta/character_voice.md').exists()


def test_busy_workspace_rejects_save_and_generation(voice_client, monkeypatch):
    client, book, _, _ = voice_client
    def busy(*_):
        raise ValueError('workspace busy')
    monkeypatch.setattr(humanware_routes, 'ensure_idle', busy, raising=False)
    for endpoint, extra in [('voice-file', {'content': 'x'}), ('generate-voice-file', {})]:
        response = client.post('/api/humanware/' + endpoint, json=payload(book, **extra))
        assert response.status_code == 409
    assert not (book / 'meta/character_voice.md').exists()


def test_scoring_is_explicitly_unsupported(voice_client):
    client, book, _, _ = voice_client
    assert client.get('/api/humanware/status', params=payload(book)).json()['scoring_supported'] is False
    response = client.post('/api/humanware/score-chapter', json=payload(book, chapter_file='story/0001/chapter.md'))
    assert response.status_code == 501
    assert 'total_score' not in response.text


def test_missing_file_and_invalid_content_are_reported_without_damage(voice_client):
    client, book, _, _ = voice_client
    assert client.get('/api/humanware/voice-file', params=payload(book)).json()['status'] == 'not_found'
    assert client.post('/api/humanware/voice-file', json=payload(book, content='nul\x00byte')).status_code == 409
    assert not (book / 'meta/character_voice.md').exists()
    (book / 'meta/character_profiles.md').write_text('没有角色标题', encoding='utf-8')
    assert client.post('/api/humanware/generate-voice-file', json=payload(book)).status_code == 409
    assert not (book / 'meta/character_voice.md').exists()


def test_plugin_rejects_file_symlink_outside_workspace(voice_client, tmp_path):
    client, book, _, _ = voice_client
    outside = tmp_path / 'outside.md'
    outside.write_text('keep', encoding='utf-8')
    try:
        (book / 'meta/character_voice.md').symlink_to(outside)
    except OSError:
        pytest.skip('Windows symlink permission unavailable')
    assert client.get('/api/humanware/voice-file', params=payload(book)).status_code == 409
    assert client.post('/api/humanware/voice-file', json=payload(book, content='changed')).status_code == 409
    assert outside.read_text(encoding='utf-8') == 'keep'


def test_individual_voice_edit_returns_profile_reference_and_preserves_other_character(voice_client):
    client, book, _, _ = voice_client
    voice = book / 'meta/character_voice.md'
    voice.write_text('# 声音\n\n## 林木\n\n寡言。\n\n## 陈枝\n\n原样保留。\n', encoding='utf-8')
    document = client.get('/api/humanware/voice-file', params=payload(book)).json()
    assert 'characters' in document, 'voice API must expose plugin-owned character views'
    assert document['characters'][0]['profile'].strip() == '沉默。'
    saved = client.post('/api/humanware/voice-character', json=payload(book,
        character_id=document['characters'][0]['id'], expected_revision=document['revision'], content='先听再说。'))
    assert saved.status_code == 200, saved.text
    assert '## 陈枝\n\n原样保留。\n' in voice.read_text(encoding='utf-8')
    retry = client.post('/api/humanware/voice-character', json=payload(book,
        character_id=document['characters'][0]['id'], expected_revision=document['revision'], content='旧页面修改'))
    assert retry.status_code == 409
    assert '先听再说。' in voice.read_text(encoding='utf-8')


def test_individual_voice_edit_respects_busy_and_owner_policy(voice_client, monkeypatch):
    client, book, manager, _ = voice_client
    voice = book / 'meta/character_voice.md'
    voice.write_text('## 林木\n旧声音', encoding='utf-8')
    document = client.get('/api/humanware/voice-file', params=payload(book)).json()
    assert 'characters' in document
    body = payload(book, character_id=document['characters'][0]['id'],
                   expected_revision=document['revision'], content='新的声音')
    manager.is_workflow_owner_enabled = lambda _: False
    assert client.post('/api/humanware/voice-character', json=body).status_code == 409
    manager.is_workflow_owner_enabled = lambda _: True
    def busy(*args):
        raise ValueError('workspace busy')
    monkeypatch.setattr(humanware_routes, 'ensure_idle', busy)
    assert client.post('/api/humanware/voice-character', json=body).status_code == 409
    assert voice.read_text(encoding='utf-8') == '## 林木\n旧声音'


def test_character_routes_check_owner_idle_and_plugin(voice_client, monkeypatch):
    client, book, manager, catalog = voice_client
    installed = catalog.resolve_file('custom-xs2', 'voice_support', 'voice_support.py').directory.parent
    sibling = Path(__file__).resolve().parents[2]
    source = next((sibling / name / 'plugins/xs2-novel-flywheel/resources/script-library/xs2'
                   for name in ('plugins', 'DeterminFlow-Plugins')
                   if (sibling / name / 'plugins/xs2-novel-flywheel').is_dir()))
    for package in ('character_center', 'story_support', 'prose_policy'):
        if (source / package).is_dir():
            shutil.copytree(source / package, installed / package)
    view = client.get('/api/humanware/characters', params=payload(book))
    assert view.status_code == 200, view.text
    assert view.json()['characters'][0]['status'] == 'legacy'
    policy = client.get('/api/humanware/prose-policy', params=payload(book)).json()
    save = payload(book, mode='narrative_led', expected_revision=policy['revision'])
    with monkeypatch.context() as guard:
        guard.setattr(manager, 'get_workflow_owner', lambda _: 'another-plugin')
        assert client.post('/api/humanware/prose-policy', json=save).status_code == 400
    with monkeypatch.context() as guard:
        def busy(*_):
            raise ValueError('workspace busy')
        guard.setattr(humanware_routes, 'ensure_idle', busy)
        response = client.post('/api/humanware/prose-policy', json=save)
        assert response.status_code == 409 and 'workspace busy' in response.text
    assert not (book / 'learning').exists()
    assert client.post('/api/humanware/prose-policy', json=save).json()['mode'] == 'narrative_led'
    assert client.get('/api/humanware/rule-audit', params=payload(book)).json()['chapter'] == '0001'
    catalog.owner_enabled = lambda _: False
    assert client.get('/api/humanware/characters', params=payload(book)).status_code == 409


def test_assistant_history_get_projects_interruption_without_a_write(voice_client, monkeypatch):
    from src.web import novel_routes
    client, book, _, catalog = voice_client
    target = book / 'learning/assistant-history.json'
    target.parent.mkdir()
    original = json.dumps({'entries': [{'id': 'interrupted', 'status': 'running', 'purpose': 'dialogue_trial'}]}).encode()
    target.write_bytes(original)
    installed = catalog.resolve_file('custom-xs2', 'voice_support', 'voice_support.py').directory.parent
    source = Path(__file__).resolve().parents[2] / 'DeterminFlow-Plugins/plugins/xs2-novel-flywheel/resources/script-library/xs2'
    shutil.copytree(source / 'console_service', installed / 'console_service')
    shutil.copytree(source / 'prose_policy', installed / 'prose_policy')
    monkeypatch.setattr(novel_routes, '_available_assistant_workflow', lambda *_: 'available')
    client.app.include_router(novel_routes.router)
    response = client.get('/api/novel-console/assistant/history', params=payload(book))
    assert response.status_code == 200, response.text
    assert response.json()['entries'][0]['error_code'] == 'interrupted'
    assert target.read_bytes() == original


def test_character_assistant_does_not_replay_request_from_another_purpose(voice_client, monkeypatch):
    from src.web import novel_routes
    client, book, _, _ = voice_client
    request_id = 'c0938ed0-d48b-4c14-a4f8-6d54d4fc9846'
    jobs = SimpleNamespace(history=lambda _: [{'id': request_id, 'status': 'completed', 'purpose': 'general'}])
    monkeypatch.setattr(novel_routes, '_assistant_jobs', lambda _: jobs)
    client.app.include_router(novel_routes.router)
    response = client.post('/api/novel-console/assistant', json=payload(
        book, request_id=request_id, purpose='dialogue_trial', question='重试'))
    assert response.status_code == 409, response.text
    assert not (book / 'learning').exists()
