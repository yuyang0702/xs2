"""Ark configuration must reach the official Chat endpoint with native parameters."""
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core import model_manager as model_manager_module
from src.core.llm_client import create_llm
from src.core.model_manager import ModelManager
from src.web.api_routes import router


@pytest.fixture
def ark_manager(tmp_path, monkeypatch):
    path = tmp_path / 'models_config.json'
    path.write_text(json.dumps({'providers': {}, 'default_params': {}}), encoding='utf-8')
    manager = ModelManager(str(path))
    monkeypatch.setattr(model_manager_module, '_model_manager', manager)
    monkeypatch.setenv('ARK_API_KEY', 'ark-test-only')
    return manager


def test_ark_can_be_added_through_settings_without_altering_existing_provider(ark_manager):
    ark_manager.add_provider('existing', {'provider_type': 'openai_compatible',
                             'name': 'Existing', 'base_url': 'https://example.test/v1',
                             'models': ['current'], 'api_key': 'old-test-key'})
    original = dict(ark_manager.get_all_providers()['existing'])
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post('/api/model-providers', json={
        'provider_id': 'volcengine', 'provider_type': 'volcengine', 'name': '火山方舟',
        'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'api_key': '${ARK_API_KEY}', 'models': ['doubao-seed-character-260628'],
    })
    assert response.status_code == 200, response.text
    assert ark_manager.get_all_providers()['existing'] == original
    reloaded = ModelManager(str(ark_manager.config_path))
    assert reloaded.get_provider_type('volcengine') == 'volcengine'
    assert reloaded.get_provider('volcengine')['api_key'] == 'ark-test-only'
    listed = client.get('/api/model-providers').json()['providers']['volcengine']
    assert listed['api_key'] == '***'
    assert listed['capabilities']['provider_type'] == 'volcengine'


@pytest.mark.parametrize('thinking,effort,expected', [
    (False, 'high', {'thinking': {'type': 'disabled'}}),
    (True, 'medium', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'medium'}),
])
def test_ark_client_sends_chat_payload_and_preserves_environment_key_reference(
    ark_manager, thinking, effort, expected,
):
    ark_manager.add_provider('volcengine', {
        'provider_type': 'volcengine', 'name': '火山方舟',
        'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'api_key': '${ARK_API_KEY}', 'models': ['doubao-seed-character-260628'],
        'hyperparameter_values': {'max_completion_tokens': 32768, 'frequency_penalty': 2},
    })
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            'id': 'ark-test', 'object': 'chat.completion', 'created': 1,
            'model': 'doubao-seed-character-260628',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '你好'},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5},
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        llm = create_llm(model_override='volcengine:doubao-seed-character-260628',
                         streaming=False, provider_retries_enabled=False,
                         http_client=client,
                         model_params={'thinking_enabled': thinking, 'reasoning_effort': effort,
                                       'presence_penalty': 1, 'temperature': 0.7})
        result = llm.invoke([('system', '你是人工智能助手。'), ('human', '你好')])
    assert result.content == '你好'
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'
    assert request.headers['authorization'] == 'Bearer ark-test-only'
    payload = json.loads(request.content)
    assert payload['model'] == 'doubao-seed-character-260628'
    assert payload['messages'] == [{'role': 'system', 'content': '你是人工智能助手。'},
                                    {'role': 'user', 'content': '你好'}]
    assert payload['thinking'] == expected['thinking']
    assert payload.get('reasoning_effort') == expected.get('reasoning_effort')
    assert payload['max_completion_tokens'] == 32768
    assert 'presence_penalty' not in payload and 'frequency_penalty' not in payload
    saved = json.loads(ark_manager.config_path.read_text(encoding='utf-8'))
    assert saved['providers']['volcengine']['api_key'] == '${ARK_API_KEY}'
