"""Execute the enabled novel plugin's role rehearsal before a body writer."""
from __future__ import annotations

import asyncio
import inspect
import logging

from src.workflow.definition import resolve_placeholders
from src.workflow.model_utils import _now_iso
from src.workflow.request_fingerprint import build_workflow_llm_request_fingerprint
from src.workflow.runtime import effective_agent_definition_sha256
from src.workflow.runtime_guards import RUNTIME_GUARD_KEY
from src.workflow.task_overrides import MODEL_PARAMS_OVERRIDE_KEY

from .base import BaseNodePlugin, NodeContext, NodeResult

logger = logging.getLogger(__name__)


class NovelRehearsalNode(BaseNodePlugin):
    node_type = "novel_rehearsal"
    label = "分角色试演"

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.agent.definition import get_agent_definition
        from src.agent.session import AgentSession
        from src.core import llm_client
        from src.core.model_manager import get_model_manager
        from src.web.novel_plugin import script_service

        config = ctx.node_def.node_params
        writer_id = config.get("writer_node")
        writer = ctx.definition.get_node(writer_id)
        slot = config.get("slot")
        if not ctx.shared_ws or writer is None or writer.node_type != "agent" or type(slot) is not int or not 0 <= slot <= 6:
            return NodeResult(status="failed", error="分角色试演缺少有效工作区、写手或场景槽。")

        values = ctx.parameter_values
        agent_type = await resolve_placeholders(writer.agent_type, values)
        override = await resolve_placeholders(writer.model_override, values)
        agent = get_agent_definition(agent_type)
        if agent is None:
            return NodeResult(status="failed", error="分角色试演找不到当前写手配置。")
        parent = getattr(ctx.session_manager, "sessions", {}).get(ctx.parent_id)
        model_id = override or agent.model or getattr(parent, "model_id", None)
        manager = get_model_manager()
        model_id = model_id or manager.get_default_model()
        if not model_id:
            return NodeResult(status="failed", error="分角色试演找不到当前写手使用的模型。")
        overrides = writer.node_params.get(MODEL_PARAMS_OVERRIDE_KEY) or {}
        model_params = {**(agent.model_params or {}), **overrides}
        guard = writer.node_params.get(RUNTIME_GUARD_KEY)
        if guard:
            if guard.get("agent_type") != agent_type or guard.get("model_override", "") != (override or ""):
                return NodeResult(status="failed", error="分角色试演的写手身份与任务快照不符。")
            try:
                ctx.session_manager.verify_effective_agent_definition(
                    agent_type, expected_sha256=guard["effective_agent_definition_sha256"],
                    model_override=override or None, model_params_override=overrides,
                )
            except (RuntimeError, ValueError) as error:
                return NodeResult(status="failed", error=str(error))

        request_params = dict(model_params)
        cap = model_params.get("max_tokens")
        request_params["max_tokens"] = min(cap, 4096) if type(cap) is int and cap > 0 else 4096
        identity = effective_agent_definition_sha256({
            "model": model_id,
            "params": request_params,
            "writer_guard": guard,
            "defaults": manager.get_default_params(),
        })
        style = await resolve_placeholders("{{pp_learning_context}}", values)
        if style.startswith("{{"):
            style = ""
        usage = AgentSession(session_type="sub", agent_type=agent_type, workflow_id=ctx.workflow_id, task_id=ctx.task_id)
        usage.node_id = ctx.node_def.id

        async def call(step, system, user, parse):
            fingerprint = build_workflow_llm_request_fingerprint(
                workflow_id=ctx.workflow_id, task_id=ctx.task_id, node_id=ctx.node_def.id,
                model=model_id, agent_type=agent_type,
                input_snapshot={"step": step, "input_sha256": effective_agent_definition_sha256([system, user])},
                model_params=request_params,
            )
            messages = [SystemMessage(content=system), HumanMessage(content=user)]
            for attempt in range(2):
                client = llm_client.create_llm(
                    model_override=model_id, model_params=request_params, streaming=True,
                    timeout=60, provider_retries_enabled=False, request_fingerprint=fingerprint,
                )
                started = _now_iso()
                try:
                    response = await asyncio.wait_for(client.ainvoke(messages), timeout=65)
                    metadata = getattr(client, "metadata", None) or {}
                    await usage._extract_and_broadcast_token_usage(
                        response, None, call_timestamp=started,
                        model_id=metadata.get("determinflow_model_id") or model_id,
                    )
                    content = response.content
                    if isinstance(content, list):
                        content = "".join(part.get("text", "") for part in content
                                          if isinstance(part, dict) and part.get("type") in {"text", "output_text"})
                    try:
                        return parse(content)
                    except (TypeError, ValueError):
                        if attempt:
                            raise ValueError(f"分角色试演的 {step} 两次返回无效结构。") from None
                        messages[0] = SystemMessage(content=system + "\n按要求返回完整纯 JSON，保留所有必填字段。")
                finally:
                    close = getattr(client, "aclose", None)
                    if callable(close):
                        closed = close()
                        if inspect.isawaitable(closed):
                            await closed

        try:
            service = script_service("character_center")
            async with asyncio.timeout(360):
                output, count = await service.prepare_rehearsal(
                    ctx.shared_ws, ctx.task_id, writer_id, values.get("chapter_number", "0001"),
                    values.get("multi_dir", ""), slot, style, call, model_identity=identity,
                )
            result = NodeResult(
                status="completed",
                summary=f"声线审核通过，已交接 {count} 场人物试演。" if count else "当前场景没有需要试演、且档案可匹配的出场人物。",
                outputs={f"rehearsal_{writer_id}": output},
            )
        except ValueError as error:
            result = NodeResult(status="failed", error=str(error))
        except Exception as error:
            logger.warning("角色试演失败 node=%s error=%s", ctx.node_def.id, type(error).__name__)
            result = NodeResult(status="failed", error=f"分角色试演未完成（{type(error).__name__}），可从本节点重试。")
        result.token_usage = usage.get_cumulative_token_usage()
        result.token_usage_calls = usage.get_token_usage_calls()
        return result
