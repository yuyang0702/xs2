"""Transport adapter for the enabled novel plugin's adviser service."""
import asyncio
from copy import deepcopy
import json
import math
from src.core.request_llm import create_request_llm as create_llm
from .novel_story_support import story_support
from .novel_plugin import console_service, script_service, workflow_resources


CHARACTER_PURPOSES = {'character_edit', 'dialogue_trial'}


def _isolated_params(values, provider_type):
    from src.core.provider_adapters import get_model_param_schema
    schema = get_model_param_schema(provider_type)
    result = {}
    for key in ('thinking_enabled', 'reasoning_effort', 'temperature', 'top_p', 'max_tokens'):
        value = values.get(key)
        field = schema.get(key, {})
        if key == 'max_tokens' and type(value) is int and 1 <= value <= 131072:
            result[key] = value
        elif field.get('type') == 'boolean' and type(value) is bool:
            result[key] = value
        elif field.get('type') == 'select' and isinstance(value, str) and value in field.get('options', []):
            result[key] = value
        elif (field.get('type') == 'range' and type(value) in (int, float)
              and field['min'] <= value <= field['max'] and math.isfinite(value)):
            result[key] = value
    return result


def character_model(request, manager, root, purpose, *, include_writer=False):
    from src.agent.definition import get_agent_definition
    from src.core.model_manager import get_model_manager
    from src.workflow.task_overrides import MODEL_PARAMS_OVERRIDE_KEY, apply_node_model_overrides
    from .novel_workflow_models import model_settings, novel_definition

    extension_manager = getattr(request.app.state, 'extension_manager', None)
    if extension_manager is None:
        raise ValueError('小说插件尚未加载。')
    roles = workflow_resources(extension_manager, manager)
    stage = 'character' if purpose == 'character_edit' else 'mvp'
    if stage not in roles:
        raise ValueError('当前小说插件缺少此任务所需的工作流。')
    definition = deepcopy(novel_definition(manager, roles[stage]))
    manifest = root / '.novel-project.json'
    if manifest != manifest.resolve():
        raise ValueError('不能通过链接读取作品模型设置。')
    state = json.loads(manifest.read_text(encoding='utf-8-sig')) if manifest.is_file() else {}
    if not isinstance(state, dict) or not isinstance(state.get('values', {}), dict):
        raise ValueError('作品模型设置格式无效。')
    production = console_service().production
    writer_type = state.get('values', {}).get('writer_type')
    choose_writer = getattr(production, 'dialogue_writer_node', None)
    if stage == 'character':
        node_id = 'agent_voice'
    elif choose_writer is not None:
        node_id = choose_writer(definition, writer_type)
    else:
        node_id = 'agent_nw' if writer_type == 'muti' else 'agent_sw'
    models = get_model_manager()
    overrides = production.model_overrides(state, definition, stage) or {}
    if node_id in overrides:
        apply_node_model_overrides(definition, {node_id: overrides[node_id]}, model_manager=models)
    setting = next((row for row in model_settings(definition, models)['nodes'] if row['id'] == node_id), None)
    if not setting or not setting['available']:
        raise ValueError('此角色写手没有可用模型，请在现有工作流模型设置中选择。')
    model = setting['effective_model']
    node = next(row for row in definition['nodes'] if row['id'] == node_id)
    agent = get_agent_definition(node.get('agent_type', 'default'))
    params = dict(agent.model_params or {}) if agent else {}
    installed_params = (node.get('node_params') or {}).get(MODEL_PARAMS_OVERRIDE_KEY)
    if isinstance(installed_params, dict):
        params.update(installed_params)
    params.update((production.model_params_overrides(state, definition, stage) or {}).get(node_id, {}))
    provider, _, name = model.partition(':')
    settings = model, _isolated_params(params, models.get_model_provider_type(provider, name))
    if not include_writer:
        return settings
    from src.session.prompt_builder import PromptBuilder
    prompt_manager = getattr(request.app.state, 'prompt_manager', None)
    if not agent or prompt_manager is None:
        raise ValueError('场景试读无法读取当前分场写手的提示。')
    writer = PromptBuilder(prompt_manager=prompt_manager).build_static_workflow_base(node['agent_type'])
    return (*settings, {'label': node.get('label', node_id), 'system': writer})


async def _receive_model_reply(llm, messages, on_output):
    return await console_service()._receive_model_reply(llm, messages, on_output)


class NovelAssistantJobs:
    def __init__(self):
        self._delegate = None

    @property
    def delegate(self):
        service = console_service()  # Recheck enabled owner even with an existing instance.
        if self._delegate is None:
            from .novel_reference_adoption import reference_catalog
            self._delegate = service.create_assistant(
                lambda **kwargs: create_llm(**kwargs),
                lambda required=False: story_support(required=required),
                catalog_loader=reference_catalog,
                character_loader=lambda: script_service('character_center'),
            )
        return self._delegate

    @property
    def tasks(self):
        return self.delegate.tasks

    @property
    def support_loader(self):
        return self.delegate.support_loader

    def history(self, root):
        return self.delegate.history(root, check_freshness=True)

    def start(self, root, request_id, payload):
        from src.runtime_admission import activity_scope
        with activity_scope("小说助手正在准备分析。"):
            return self.delegate.start(root, request_id, payload)

    def _write(self, root, entries):
        return self.delegate._write(root, entries)
