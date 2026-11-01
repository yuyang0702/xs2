from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extension_host.resource_ids import ResourceIdResolver, build_resource_id_plan


def test_console_uses_installed_owner_identity_and_rejects_disabled_owner():
    from src.web.novel_plugin import workflow_resources
    resolver = ResourceIdResolver()
    resolver.register(build_resource_id_plan('xs2-novel-flywheel', 'my-library',
                                           {'workflows': ['build', 'character', 'mvp']}))
    manager = SimpleNamespace(resource_resolver=resolver, is_running=lambda owner: True)
    workflows = SimpleNamespace(list_workflows=lambda: {'workflows': [
        {'workflow_id': 'my-library-build'}, {'workflow_id': 'my-library-character'},
        {'workflow_id': 'my-library-mvp'}, {'workflow_id': 'another-mvp'}]})
    assert workflow_resources(manager, workflows) == {
        'build': 'my-library-build', 'character': 'my-library-character', 'mvp': 'my-library-mvp'}
    manager.is_running = lambda owner: False
    with pytest.raises(ValueError, match='插件'):
        workflow_resources(manager, workflows)


def test_console_service_comes_from_enabled_catalog_not_a_developer_path(tmp_path, monkeypatch):
    from src.web import novel_plugin
    from src.workflow.script_library import ScriptLibraryCatalog
    from src.extension_api.registrar import OwnedPath
    root = tmp_path / 'extension'
    helper = root / 'renamed-xs2' / 'console_service'
    helper.mkdir(parents=True)
    (helper / 'console_service.py').write_text('VALUE = "plugin-owned"', encoding='utf-8')
    enabled = True
    catalog = ScriptLibraryCatalog(tmp_path / 'user', [OwnedPath('xs2-novel-flywheel', root)],
                                   owner_enabled=lambda owner: enabled)
    monkeypatch.setattr(novel_plugin, 'get_script_library', lambda: catalog)
    assert novel_plugin.console_service().VALUE == 'plugin-owned'
    enabled = False
    with pytest.raises(ValueError, match='插件'):
        novel_plugin.console_service()


def test_renamed_reader_task_is_used_for_chapter_context_and_busy_guard(tmp_path):
    import json
    from src.web.novel_chapters import chapter_tasks
    from src.web.novel_repair import ensure_idle
    root = tmp_path / 'book'
    root.mkdir()
    workflows = tmp_path / 'workflows'
    folder = workflows / 'custom-reader-sim'
    (folder / 'tasks').mkdir(parents=True)
    (folder / '.extension.json').write_text(json.dumps({'owner': 'xs2-novel-flywheel'}))
    task = {'task_id': 'one', 'workflow_id': 'custom-reader-sim', 'status': 'running',
            'workspace_override': str(root), 'parameter_values': {'chapter_number': '0001'}}
    (folder / 'tasks/one.json').write_text(json.dumps(task))
    assert chapter_tasks(root, workflows, '0001')['reader-sim']['workflow_id'] == 'custom-reader-sim'
    with pytest.raises(ValueError, match='处理'):
        ensure_idle(root, workflows)


@pytest.mark.parametrize('condition', ['disabled', 'missing_workflow', 'missing_service'])
def test_unavailable_adviser_returns_503_before_workspace_or_model_work(tmp_path, monkeypatch, condition):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.web import novel_routes
    resolver = ResourceIdResolver()
    resolver.register(build_resource_id_plan('xs2-novel-flywheel', 'custom',
                                            {'workflows': ['build', 'novel-advisor']}))
    def unexpected(*args, **kwargs):
        pytest.fail('Unavailable adviser must not resolve/mutate a workspace or launch analysis')
    manager = SimpleNamespace(
        get_workflow_execution_policy=lambda _: 'public',
        is_workflow_owner_enabled=lambda _: condition != 'disabled',
        list_workflows=lambda: [{'workflow_id': 'custom-build'}] + (
            [] if condition == 'missing_workflow' else [{'workflow_id': 'custom-novel-advisor'}]),
        _ws_manager=SimpleNamespace(resolve_workflow_workspace=unexpected),
    )
    extension = SimpleNamespace(resource_resolver=resolver, is_running=lambda _: condition != 'disabled')
    def service():
        if condition == 'missing_service':
            raise ValueError('小说插件的工作台服务尚未加载，请检查插件状态并重新启动。')
        return SimpleNamespace(create_assistant=unexpected)
    monkeypatch.setattr(novel_routes, 'console_service', service)
    app = FastAPI(); app.include_router(novel_routes.router)
    app.state.workflow_manager = manager; app.state.extension_manager = extension
    client = TestClient(app, raise_server_exceptions=False)
    context = {'workflow_id': 'custom-build', 'workspace': str(tmp_path / 'not-created')}
    history = client.get('/api/novel-console/assistant/history', params=context)
    submit = client.post('/api/novel-console/assistant', json={**context,
        'request_id': 'c0938ed0-d48b-4c14-a4f8-6d54d4fc9846', 'question': '分析', 'purpose': 'advisor'})
    for response in (history, submit):
        assert response.status_code == 503, response.text
        assert '插件' in response.json()['detail']
    assert not (tmp_path / 'not-created').exists()
