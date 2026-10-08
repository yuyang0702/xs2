"""Model choices for novel steps, persisted in their real Workflow definitions."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from fastapi import HTTPException

from src.agent.definition import get_agent_definition
from src.workflow.task_overrides import apply_node_model_overrides, TaskOverrideValidationError

PREFIX = "xs2-novel-flywheel-"


def novel_definition(manager, workflow_id: str) -> dict:
    if not workflow_id.startswith(PREFIX):
        raise HTTPException(400, "这里只能调整小说工作台的步骤模型。")
    workflow = manager.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "该小说工作流不可用，请刷新工作流或检查插件状态。")
    return workflow["definition"]


def definition_digest(definition: dict) -> str:
    return hashlib.sha256(json.dumps(definition, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def model_settings(definition: dict, model_manager) -> dict:
    """Return only model identities, never Provider credentials or Agent prompts."""
    configured = model_manager.get_all_models()
    rows = []
    for node in definition.get("nodes", []):
        if node.get("node_type", "agent") != "agent":
            continue
        override = node.get("model_override") or ""
        binding = (node.get("var_bindings") or {}).get("model_override") or {}
        dynamic = bool(binding.get("var_key") or "{{" in override or "{{" in node.get("agent_type", ""))
        agent = get_agent_definition(node.get("agent_type", "default"))
        inherited = (agent.model if agent else None) or model_manager.get_default_model() or ""
        effective = override or inherited
        # Legacy Agent configurations may store a bare model name. Match the
        # same first configured Provider used by create_llm, without changing it.
        if effective and ":" not in effective and not dynamic:
            effective = next((model for model in configured if model.partition(":")[2] == effective), effective)
        rows.append({
            "id": node["id"], "label": node.get("label") or node["id"],
            "override": override, "effective_model": "" if dynamic else effective,
            "source": "parameter" if dynamic else "workflow" if override else "agent" if agent and agent.model else "system",
            "editable": not dynamic,
            "available": bool(not dynamic and effective in configured),
            "condition": node.get("execution_condition") or "",
        })
    return {"workflow_id": definition["workflow_id"], "version": definition.get("version", 1),
            "digest": definition_digest(definition), "nodes": rows}


def save_model_settings(manager, workflow_id: str, expected_digest: str,
                        choices: dict[str, str], model_manager) -> dict:
    current = novel_definition(manager, workflow_id)
    if definition_digest(current) != expected_digest:
        raise HTTPException(409, "工作流已被更新。请重新读取模型设置后再保存，避免覆盖其他修改。")
    updated = deepcopy(current)
    nodes = {node["id"]: node for node in updated.get("nodes", [])}
    for node_id, model in choices.items():
        node = nodes.get(node_id)
        if not node or node.get("node_type", "agent") != "agent":
            raise HTTPException(400, "只能为本步骤已有的 AI 节点选择模型。")
        binding = (node.get("var_bindings") or {}).get("model_override") or {}
        if binding.get("var_key") or "{{" in (node.get("model_override") or "") or "{{" in node.get("agent_type", ""):
            raise HTTPException(409, "该节点的模型由工作流参数绑定，请在原有参数设置中调整。")
        if not isinstance(model, str):
            raise HTTPException(400, "模型选择必须是文本。")
    choices = {node_id: model.strip() for node_id, model in choices.items()}
    try:
        apply_node_model_overrides(updated, {key: value for key, value in choices.items() if value},
                                   model_manager=model_manager)
    except TaskOverrideValidationError as error:
        raise HTTPException(400, str(error)) from error
    for node_id, model in choices.items():
        if not model:
            nodes[node_id]["model_override"] = ""
    if updated != current:
        if manager.update_workflow(workflow_id, updated) is None:
            raise HTTPException(409, "模型设置没有保存成功，请刷新后重试。")
    # Read from disk through the manager, just as future create_task does.
    saved = novel_definition(manager, workflow_id)
    for node_id, model in choices.items():
        actual = next(node for node in saved["nodes"] if node["id"] == node_id)
        if (actual.get("model_override") or "") != model:
            raise HTTPException(409, "模型配置回读校验未通过，请重新读取后检查。")
    return model_settings(saved, model_manager)
