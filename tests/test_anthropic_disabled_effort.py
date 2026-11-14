from copy import deepcopy
import json

import pytest

from src.core.model_manager import ModelManager
from src.core.provider_adapters import build_provider_request


def test_disabled_cross_provider_none_effort_is_not_forwarded_or_persisted():
    params = {"thinking_enabled": False, "reasoning_effort": "none"}
    before = deepcopy(params)
    request = build_provider_request("anthropic", params, {})
    assert request["client_kwargs"]["thinking"] == {"type": "disabled"}
    assert "output_config" not in request["client_kwargs"]
    assert params == before


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_valid_effort_is_preserved_even_when_thinking_disabled(effort):
    request = build_provider_request(
        "anthropic", {"thinking_enabled": False, "reasoning_effort": effort}, {}
    )
    assert request["client_kwargs"]["output_config"] == {"effort": effort}


@pytest.mark.parametrize("thinking", [True, None])
def test_none_effort_requires_explicit_disabled_thinking(thinking):
    with pytest.raises(ValueError, match="Unsupported Anthropic reasoning_effort"):
        build_provider_request(
            "anthropic", {"thinking_enabled": thinking, "reasoning_effort": "none"}, {}
        )


def test_unknown_effort_remains_rejected_when_thinking_disabled():
    with pytest.raises(ValueError, match="Unsupported Anthropic reasoning_effort"):
        build_provider_request(
            "anthropic", {"thinking_enabled": False, "reasoning_effort": "invalid"}, {}
        )


@pytest.mark.parametrize(
    ("model", "params", "thinking", "effort"),
    [
        ("claude-opus-5-5", {"thinking_enabled": False, "reasoning_effort": "none"},
         {"type": "adaptive"}, "low"),
        ("claude-opus-5-5", {"thinking_enabled": True, "thinking_budget": 2048,
                             "reasoning_effort": "high"}, {"type": "adaptive"}, "high"),
        ("claude-opus-4-6", {"thinking_enabled": False, "reasoning_effort": "none"},
         {"type": "disabled"}, None),
    ],
)
def test_anthropic_workflow_thinking_matches_selected_model(tmp_path, model, params, thinking, effort):
    config_path = tmp_path / "models.json"
    config_path.write_text(json.dumps({"providers": {"claude": {"provider_type": "anthropic"}}}),
                           encoding="utf-8")
    manager = ModelManager(str(config_path))
    before = deepcopy(params)

    kwargs = manager.build_provider_request("claude", params, model_name=model)["client_kwargs"]

    assert kwargs["thinking"] == thinking
    assert kwargs.get("output_config") == ({"effort": effort} if effort else None)
    assert params == before
