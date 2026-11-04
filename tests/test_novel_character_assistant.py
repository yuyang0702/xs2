"""AI role selection reads the book and rejects unconfigured model references."""
import json
from types import SimpleNamespace

import pytest

from src.web import novel_assistant


def test_selected_role_uses_only_saved_book_model_and_supported_params(tmp_path, monkeypatch):
    from src.core import model_manager

    class Models:
        def get_all_models(self):
            return ['p:book', 'p:writer', 'p:voice']

        def get_default_model(self):
            return 'p:writer'

        def get_provider(self, provider):
            return {'models': ['book', 'writer', 'voice']} if provider == 'p' else None

        def get_model_provider_type(self, *_):
            return 'openai'

    monkeypatch.setattr(model_manager, 'get_model_manager', Models)
    definitions = {
        'custom-character': {'workflow_id': 'custom-character', 'nodes': [
            {'id': 'agent_voice', 'model_override': 'p:voice'}]},
        'custom-mvp': {'workflow_id': 'custom-mvp', 'nodes': [
            {'id': 'agent_sw', 'model_override': 'p:writer',
             'node_params': {'_model_params_override': {'temperature': 0.1, 'top_p': 0.91}}},
            {'id': 'agent_nw', 'model_override': 'p:writer'}]},
    }
    manager = SimpleNamespace(get_workflow_owner=lambda _: 'xs2-novel-flywheel',
                              get_workflow=lambda identity: {'definition': definitions[identity]})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(extension_manager=object())))
    monkeypatch.setattr(novel_assistant, 'workflow_resources', lambda *_: {'character': 'custom-character', 'mvp': 'custom-mvp'})
    from types import ModuleType
    production = ModuleType('production')
    production.model_overrides = lambda state, _definition, stage: {'agent_sw': state['writerModel']} if stage == 'mvp' else {}
    production.model_params_overrides = lambda state, _definition, stage: {'agent_sw': state['writerModelParams']} if stage == 'mvp' else {}
    monkeypatch.setattr(novel_assistant, 'console_service', lambda: SimpleNamespace(production=production))
    project = tmp_path / '.novel-project.json'
    values = {'writerModel': 'p:book', 'values': {'writer_type': 'single'},
              'writerModelParams': {'temperature': 0.55, 'api_key': 'outside scope', 'reasoning_effort': 'invalid'}}
    project.write_text(json.dumps(values), encoding='utf-8')
    assert novel_assistant.character_model(request, manager, tmp_path, 'dialogue_trial') == (
        'p:book', {'temperature': 0.55, 'top_p': 0.91})
    assert novel_assistant.character_model(request, manager, tmp_path, 'character_edit') == ('p:voice', {})
    project.write_text(json.dumps(values | {'writerModel': 'p:missing'}), encoding='utf-8')
    with pytest.raises(ValueError):
        novel_assistant.character_model(request, manager, tmp_path, 'dialogue_trial')

def test_dialogue_trial_uses_plugin_selected_scene_writer(monkeypatch, tmp_path):
    # Reuse the real role selection flow while exposing two installed agent roles.
    from src.core import model_manager

    class Models:
        def get_all_models(self):
            return ['p:planner', 'p:scene']

        def get_default_model(self):
            return 'p:planner'

        def get_provider(self, provider):
            return {'models': ['planner', 'scene']} if provider == 'p' else None

        def get_model_provider_type(self, *_):
            return 'openai'

    monkeypatch.setattr(model_manager, 'get_model_manager', Models)
    definition = {'workflow_id': 'custom-mvp', 'nodes': [
        {'id': 'agent_nw', 'model_override': 'p:planner'},
        {'id': 'agent_dw', 'model_override': 'p:scene'}]}
    manager = SimpleNamespace(get_workflow_owner=lambda _: 'xs2-novel-flywheel',
                              get_workflow=lambda _: {'definition': definition})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(extension_manager=object())))
    monkeypatch.setattr(novel_assistant, 'workflow_resources', lambda *_: {'mvp': 'custom-mvp'})
    production = SimpleNamespace(dialogue_writer_node=lambda *_: 'agent_dw',
                                 model_overrides=lambda *_: {}, model_params_overrides=lambda *_: {})
    monkeypatch.setattr(novel_assistant, 'console_service', lambda: SimpleNamespace(production=production))
    (tmp_path / '.novel-project.json').write_text(json.dumps({'values': {'writer_type': 'muti'}}), encoding='utf8')
    assert novel_assistant.character_model(request, manager, tmp_path, 'dialogue_trial')[0] == 'p:scene'
