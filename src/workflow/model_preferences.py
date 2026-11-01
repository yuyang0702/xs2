"""User model choices are independent of distributable workflow templates."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

MODEL_PREFERENCES_FILE = ".user-models.json"


def atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_model_preferences(workflow_dir: Path) -> dict[str, str]:
    path = workflow_dir / MODEL_PREFERENCES_FILE
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    choices = data.get("node_models")
    if data.get("version") != 1 or not isinstance(choices, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in choices.items()
    ):
        raise ValueError(f"Invalid workflow model preferences: {path}")
    return choices


def write_model_preferences(workflow_dir: Path, choices: dict[str, str]) -> None:
    atomic_write(workflow_dir / MODEL_PREFERENCES_FILE, json.dumps(
        {"version": 1, "node_models": choices}, ensure_ascii=False, indent=2,
    ).encode("utf-8"))


def apply_model_preferences(definition: dict, choices: dict[str, str]) -> dict:
    result = deepcopy(definition)
    for node in result.get("nodes", []):
        if node.get("id") not in choices or node.get("node_type", "agent") != "agent":
            continue
        binding = (node.get("var_bindings") or {}).get("model_override") or {}
        # An upstream parameter binding takes precedence over a stale preference.
        if binding.get("var_key") or "{{" in (node.get("model_override") or "") or "{{" in node.get("agent_type", ""):
            continue
        node["model_override"] = choices[node["id"]]
    return result
