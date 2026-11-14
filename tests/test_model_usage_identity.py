"""Invocation identity must survive provider defaults and workflow persistence."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from src.agent.session import AgentSession
from src.core.graph_builder import build_graph
from src.core.llm_client import create_llm
from src.core.model_manager import ModelManager
from src.workflow.runtime_models import NodeExecutionState, _node_state_from_dict, _node_state_to_dict
from src.workflow.token_usage import aggregate_token_usage
from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext


@pytest.mark.parametrize("requested", [None, "gpt-test", "missing-model", "relay:gpt-test"])
def test_actual_provider_call_identity_survives_default_resolution_and_persistence(tmp_path, monkeypatch, requested):
    config_path = tmp_path / "models.json"
    config_path.write_text(json.dumps({
        "default_params": {},
        "retry": {"max_retries": 0, "delays": []},
        "providers": {"relay": {
            "name": "Test relay", "provider_type": "openai_compatible",
            "base_url": "https://relay.example.test/v1", "api_key": "test-key",
            "models": ["gpt-test"],
        }},
    }), encoding="utf-8")
    manager = ModelManager(str(config_path))
    monkeypatch.setattr(manager, "get_default_model", lambda: "relay:gpt-test")
    monkeypatch.setattr("src.core.model_manager.get_model_manager", lambda: manager)

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        body = {
            "id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "gpt-test", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "done"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        }
        return httpx.Response(200, json=body)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            llm = create_llm(
                model_override=requested, streaming=False, http_async_client=client,
                metadata={"caller": "preserved", "determinflow_model_id": "stale:model"},
            )
            session = AgentSession(session_id="identity-session", session_type="sub", agent_type="test.writer")
            session.model_id = requested
            session.lc_messages = [HumanMessage(content="write")]
            session.compiled_graph = build_graph(llm=llm, tools=[]).compile()

            async def no_io(*_args, **_kwargs):
                pass

            monkeypatch.setattr(session, "async_save", no_io)
            monkeypatch.setattr(session, "_check_and_compress_messages", no_io)
            await session._invoke_graph_once("", None, max_rounds=1, append_input=False)
            return session, llm.metadata

    session, metadata = asyncio.run(scenario())
    assert requests[0]["model"] == "gpt-test"
    assert metadata["caller"] == "preserved"
    restored = AgentSession.from_dict(session.to_dict())
    calls = restored.get_token_usage_calls()
    assert [(call["provider"], call["model"], call["model_id"]) for call in calls] == [
        ("relay", "gpt-test", "relay:gpt-test"),
    ]
    assert restored.token_usage["model_id"] == "relay:gpt-test"
    assert set(restored.get_cumulative_token_usage()) == {"relay:gpt-test"}
    state = _node_state_from_dict(_node_state_to_dict(NodeExecutionState(
        node_id="writer", status="completed", session_id=restored.session_id,
        token_usage=restored.get_cumulative_token_usage(), token_usage_calls=calls,
    )), node_id="writer")
    aggregate = aggregate_token_usage({"writer": state}, {"writer": "test.writer"})
    assert aggregate["calls"][0]["model_id"] == "relay:gpt-test"
    assert aggregate["by_model"]["relay:gpt-test"]["total_tokens"] == 15


def test_session_tracks_each_run_model_across_child_calls_and_replayed_end_events(monkeypatch):
    output = AIMessage(content="done", usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5})
    events = [
        {"event": "on_chat_model_start", "run_id": "outer", "metadata": {"determinflow_model_id": "primary:writer"}},
        {"event": "on_chat_model_start", "run_id": "child", "metadata": {"determinflow_model_id": "fallback:reviewer"}},
        {"event": "on_chat_model_stream", "run_id": "child", "data": {"chunk": AIMessageChunk(content="")}},
        {"event": "on_chat_model_stream", "run_id": "child", "data": {"chunk": AIMessageChunk(content="", additional_kwargs={"reasoning_content": "reason"})}},
        {"event": "on_chat_model_stream", "run_id": "child", "data": {"chunk": AIMessageChunk(content="do")}},
        {"event": "on_chat_model_stream", "run_id": "child", "data": {"chunk": AIMessageChunk(content="ne")}},
        {"event": "on_chat_model_end", "run_id": "child", "data": {"output": output}},
        {"event": "on_chat_model_end", "run_id": "outer", "data": {"output": output}},
        {"event": "on_chat_model_end", "run_id": "child", "data": {"output": output}},
        {"event": "on_chat_model_end", "run_id": "retry", "metadata": {"determinflow_model_id": "backup:writer"}, "data": {"output": output}},
    ]

    class EventGraph:
        async def astream_events(self, *_args, **_kwargs):
            for event in events:
                yield event

    async def no_io(*_args, **_kwargs):
        pass

    session = AgentSession(session_type="sub", agent_type="test.writer")
    session.model_id = "stale:configured"
    session.compiled_graph = EventGraph()
    monkeypatch.setattr(session, "async_save", no_io)
    monkeypatch.setattr(session, "_check_and_compress_messages", no_io)
    asyncio.run(session._invoke_graph_once("", None, max_rounds=1, append_input=False))
    assert [(call["run_id"], call["model_id"]) for call in session.get_token_usage_calls()] == [
        ("child", "fallback:reviewer"), ("outer", "primary:writer"), ("retry", "backup:writer"),
    ]
    assert sum(row["call_count"] for row in session.get_cumulative_token_usage().values()) == 3
    child, outer, _ = AgentSession.from_dict(session.to_dict()).get_token_usage_calls()
    assert child["timestamp"] <= child["first_output_at"] <= child["first_text_at"] <= child["last_text_at"] <= child["completed_at"]
    assert "first_text_at" not in outer


def test_restoring_historical_unknown_model_usage_does_not_guess_from_current_settings():
    stored = AgentSession(session_id="historic", agent_type="test.writer").to_dict()
    stored["model_id"] = "current:configuration"
    stored["token_usage_calls"] = [{"call_id": "historic:1", "model_id": "unknown", "provider": "unknown", "model": "unknown"}]
    restored = AgentSession.from_dict(stored)
    assert restored.get_token_usage_calls() == stored["token_usage_calls"]


@pytest.mark.parametrize("completion_status", ["success", "failure"])
def test_agent_node_returns_call_ledger_when_completed_session_has_left_hot_cache(completion_status):
    session = AgentSession(session_id="cold-session", agent_type="test.writer")
    session.record = [{"type": "assistant", "content": "done"}]
    output = AIMessage(content="done", usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5})
    asyncio.run(session._extract_and_broadcast_token_usage(output, None, model_id="relay:writer"))

    class SessionManager:
        sessions = {}

        def get_session(self, session_id):
            return session if session_id == "cold-session" else None

        async def create_sub_session(self, **kwargs):
            kwargs["on_auto_complete"]("cold-session", "done", completion_status, "")
            return {"success": True, "session_id": "cold-session"}

    node = WorkflowNode(id="writer", node_type="agent", agent_type="test.writer", first_message="write", auto_flow=True)
    result = asyncio.run(AgentNode().execute(NodeContext(
        definition=WorkflowDef(workflow_id="workflow", nodes=[node]), node_def=node,
        node_state=NodeExecutionState(node_id="writer"), workflow_id="workflow", task_id="task",
        session_manager=SessionManager(),
    )))
    assert result.status == ("completed" if completion_status == "success" else "failed")
    assert result.token_usage_calls == session.get_token_usage_calls()
    assert result.token_usage["relay:writer"]["total_tokens"] == 5
