from copy import deepcopy

import pytest

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
