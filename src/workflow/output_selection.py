"""Opt-in structured output bound to a current-turn completion tool message."""
from __future__ import annotations

import json
import re


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-JSON numeric constant: {value}")


def _json_document(text):
    if not isinstance(text, str):
        raise ValueError("output must be text")
    text = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    return json.loads(fence.group(1) if fence else text, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)


def select_agent_output(record: list[dict], params: dict) -> tuple[str, str]:
    latest = next((m.get("content", "") for m in reversed(record) if m.get("type") == "assistant"), "")
    latest = latest if isinstance(latest, str) else ""
    policy = params.get("output_selection", "latest_message")
    if policy == "latest_message":
        return latest, ""
    if policy != "completion_tool_message":
        return "", "unknown output_selection policy"
    # Only this request's messages may participate. Never recover from old turns.
    start = next((i + 1 for i in range(len(record) - 1, -1, -1) if record[i].get("type") == "user"), len(record))
    turn = record[start:]
    calls = [(i, m, c) for i, m in enumerate(turn) if m.get("type") == "assistant"
             for c in m.get("tool_calls", [])
             if c.get("function", {}).get("name") == "complete_task"]
    if len(calls) > 1:
        return "", "ambiguous completion calls"
    candidate = latest
    if calls:
        index, candidate_message, call = calls[0]
        try:
            args = call["function"].get("arguments", {})
            args = json.loads(args) if isinstance(args, str) else args
            if args.get("status") != "success" or args.get("artifact_path"):
                raise ValueError("completion must succeed with inline output")
            results = [m for m in turn[index + 1:] if m.get("type") == "tool" and m.get("tool_call_id") == call.get("id")]
            if not call.get("id") or len(results) != 1:
                raise ValueError("missing or ambiguous completion result")
            if results[0].get("status") in {"failed", "error", "rejected"} or results[0].get("tool_status") in {"failed", "error", "rejected"}:
                raise ValueError("completion tool rejected output")
            result = json.loads(results[0].get("content", ""))
            if result.get("success") is not True or result.get("status") != "success":
                raise ValueError("completion tool rejected output")
            candidate = candidate_message.get("content", "")
        except (ValueError, TypeError, AttributeError) as exc:
            return "", str(exc)
    try:
        data = _json_document(candidate)
        # An extra structured assistant response makes the intended artifact ambiguous.
        structured = 0
        for message in turn:
            if message.get("type") == "assistant":
                try:
                    _json_document(message.get("content"))
                    structured += 1
                except (ValueError, TypeError):
                    pass
        if structured != 1:
            raise ValueError("expected exactly one structured assistant output")
        required = params.get("json_required_fields", [])
        if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
            raise ValueError("invalid json_required_fields")
        if required and (not isinstance(data, dict) or any(key not in data for key in required)):
            raise ValueError("structured output missing required fields")
        schema = params.get("json_output_schema")
        if schema is not None:
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import SchemaError, ValidationError
            try:
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(data)
            except (SchemaError, ValidationError) as exc:
                raise ValueError(f"JSON schema validation failed: {exc.message}") from exc
        return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), ""
    except (ValueError, TypeError) as exc:
        return "", f"invalid structured output: {exc}"
