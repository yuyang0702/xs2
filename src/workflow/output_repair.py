"""Workflow Agent 输出文件的确定性规范化。

LLM 输出校验失败必须结束当前 Node attempt。这里仅保留不会再次调用模型的
本地 JSON 安全修复；失败后的重新生成统一由节点失败策略创建新 attempt。
"""

from __future__ import annotations

import json
import re

from .json_output import JsonValidationResult, get_json_policy, validate_and_format_json


def validate_single_string_envelope(text: str, field: str, repair: bool) -> JsonValidationResult:
    """Adapt only an explicitly declared, complete one-string object envelope."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate object member")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("invalid numeric constant")

    def load(value):
        return json.loads(value, object_pairs_hook=pairs, parse_constant=reject_constant)

    def finish(data, repairs):
        if not isinstance(data, dict) or set(data) != {field} or not isinstance(data[field], str):
            raise ValueError("expected exactly the configured string field")
        return JsonValidationResult(success=True, data=data,
            formatted=json.dumps(data, ensure_ascii=False, indent=2), repairs=repairs)

    try:
        if not isinstance(field, str) or not field:
            raise ValueError("json_single_string_field must name a field")
        try:
            data = load(text)
        except (ValueError, TypeError):
            if not repair:
                raise ValueError("invalid single-string JSON") from None
        else:
            return finish(data, [])
        candidate = text.strip()
        repairs = []
        if candidate.startswith('```'):
            fence = re.fullmatch(r'```(?:json|JSON)?\s*\n(.*?)\n```', candidate, re.DOTALL)
            if not fence or candidate.count('```') != 2:
                raise ValueError("expected a single whole-document fence")
            candidate = fence.group(1).strip()
            repairs.append("strip_markdown_fence")
            try:
                data = load(candidate)
            except ValueError:
                pass
            else:
                return finish(data, repairs)
        key = re.escape(json.dumps(field, ensure_ascii=False))
        envelope = re.fullmatch(r'\{\s*' + key + r'\s*:\s*"(.*)"\s*\}', candidate, re.DOTALL)
        if not envelope:
            raise ValueError("expected a complete configured single-string envelope")
        body = envelope.group(1)
        # A closing prose quote followed by a comma is not an object member.
        # Extra/duplicate members still contain a quoted key followed by a
        # colon; reject those, and all nested container syntax, before repair.
        if any(char in body for char in '{}[]') or re.search(r'"\s*:', body):
            raise ValueError("ambiguous structure inside single-string envelope")
        escaped, index = [], 0
        while index < len(body):
            char = body[index]
            if char == '\\':
                token = re.match(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})', body[index:])
                if token is None:
                    raise ValueError("unknown or incomplete string escape")
                escaped.append(token.group()); index += len(token.group()); continue
            escaped.append(json.dumps(char, ensure_ascii=False)[1:-1] if char == '"' or ord(char) < 32 else char)
            index += 1
        repairs.append("single_string_envelope")
        return finish(load('{' + json.dumps(field, ensure_ascii=False) + ':"' + ''.join(escaped) + '"}'), repairs)
    except (ValueError, TypeError) as exc:
        return JsonValidationResult(success=False, error=str(exc))


async def prepare_json_file_output(
    *,
    raw_output: str,
    node_params: dict | None,
    output_file_path: str,
) -> dict:
    """校验 JSON 文件输出，只允许当前 attempt 内的确定性安全修复。"""
    policy = get_json_policy(output_file_path, node_params)
    meta: dict[str, str] = {
        "_json_repair_policy": policy,
        "_json_output_file": output_file_path,
        "_json_retry_attempts": "0",
    }
    params = node_params or {}
    allow_safe_repair = policy in {"safe_repair", "safe_repair_then_retry"}
    if "json_single_string_field" in params:
        result = validate_single_string_envelope(raw_output, params["json_single_string_field"], allow_safe_repair)
    else:
        if policy == "none":
            return {"success": True, "text": raw_output, "meta": meta}
        result = validate_and_format_json(raw_output, repair=allow_safe_repair)
    if result.success:
        if result.repairs:
            meta["_json_repair_applied"] = ",".join(result.repairs)
        return {"success": True, "text": result.formatted, "meta": meta}

    return {
        "success": False,
        "error": f"JSON 输出校验失败 [invalid_json]: {result.error}",
        "meta": meta,
    }
