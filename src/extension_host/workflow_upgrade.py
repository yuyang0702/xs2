"""Conservative migration of historical model-only edits, with trusted bases."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from src.workflow.definition import WorkflowDef
from src.workflow.model_preferences import (
    MODEL_PREFERENCES_FILE, atomic_write, read_model_preferences, write_model_preferences,
)

BASE_FILE = ".extension-base.json"
_MISSING = object()


def _with_defaults(raw, defaults):
    """Add serialization defaults without discarding unknown user fields."""
    if isinstance(raw, dict) and isinstance(defaults, dict):
        return {key: _with_defaults(raw[key], defaults.get(key)) if key in raw else value
                for key, value in {**defaults, **raw}.items()}
    if isinstance(raw, list) and isinstance(defaults, list) and len(raw) == len(defaults):
        return [_with_defaults(item, defaults[index]) for index, item in enumerate(raw)]
    return deepcopy(raw)


def model_only_changes(base: dict, current: dict) -> dict[str, str] | None:
    """Return model deltas iff every other change is an editor serialization default."""
    base_full = _with_defaults(base, WorkflowDef.from_dict(base).to_dict())
    current_full = _with_defaults(current, WorkflowDef.from_dict(current).to_dict())
    for value in (base_full, current_full):
        for key in ("version", "created_at", "updated_at"):
            value.pop(key, None)
    base_nodes = {node["id"]: node for node in base_full.get("nodes", [])}
    choices = {}
    for node in current_full.get("nodes", []):
        original = base_nodes.get(node["id"])
        if original is None:
            continue
        old_model, new_model = original.get("model_override", ""), node.get("model_override", "")
        if old_model != new_model:
            if node.get("node_type", "agent") != "agent" or not isinstance(new_model, str):
                return None
            choices[node["id"]] = new_model
            node["model_override"] = old_model
    return choices if current_full == base_full else None


def trusted_base(workflow_dir: Path, installed_hash: str, legacy_base: Path | None = None) -> dict | None:
    for path in (workflow_dir / BASE_FILE, legacy_base):
        if path is None or not path.is_file():
            continue
        raw = path.read_bytes()
        if installed_hash and hashlib.sha256(raw).hexdigest() == installed_hash:
            try:
                value = json.loads(raw)
                return value if isinstance(value, dict) else None
            except (ValueError, UnicodeDecodeError):
                pass
    return None


def migrate_model_edits(target: Path, source: Path, installed_hash: str, legacy_base: Path | None = None) -> bool:
    base = trusted_base(target.parent, installed_hash, legacy_base)
    if base is None:
        return False
    try:
        choices = model_only_changes(base, json.loads(target.read_text(encoding="utf-8")))
        if choices is None:
            return False
        existing = read_model_preferences(target.parent)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    backup = target.parent / ".upgrade-backups" / uuid.uuid4().hex
    backup.mkdir(parents=True)
    for name in ("definition.json", ".extension.json", BASE_FILE, MODEL_PREFERENCES_FILE):
        path = target.parent / name
        if path.exists():
            shutil.copy2(path, backup / name)
    # Write preferences first: an interrupted migration leaves the original
    # template usable. Existing separated choices are the more recent authority.
    if choices:
        write_model_preferences(target.parent, {**choices, **existing})
    atomic_write(target, source.read_bytes())
    return True


def _merge_reviewed(base, local, upstream, path, conflicts, resolutions):
    if local == base:
        return upstream
    if upstream == base or local == upstream:
        return local
    if path.endswith("/first_message") and all(isinstance(value, str) for value in (base, local, upstream)):
        # The editor and plugin can both append instructions. Keep both when
        # their original message is byte-for-byte the same.
        if base and local.startswith(base + "\n") and upstream.startswith(base + "\n"):
            local_tail, upstream_tail = local[len(base):], upstream[len(base):]
            if upstream_tail.startswith(local_tail):
                return upstream
            if local_tail.startswith(upstream_tail):
                return local
            return local + upstream_tail
    if all(isinstance(value, dict) for value in (base, local, upstream)):
        result = {}
        for key in dict.fromkeys([*upstream, *local, *base]):
            value = _merge_reviewed(base.get(key, _MISSING), local.get(key, _MISSING), upstream.get(key, _MISSING),
                                    path + "/" + key, conflicts, resolutions)
            if value is not _MISSING:
                result[key] = value
        return result
    if all(isinstance(value, list) for value in (base, local, upstream)) and path in {
        "/nodes", "/edges", "/gateways", "/variables", "/execution_schemes",
    }:
        key = "key" if path == "/variables" else "id"
        if all(isinstance(item, dict) and key in item for values in (base, local, upstream) for item in values):
            mapped = [{item[key]: item for item in values} for values in (base, local, upstream)]
            if all(len(items) == len(values) for items, values in zip(mapped, (base, local, upstream))):
                return list(_merge_reviewed(*mapped, path, conflicts, resolutions).values())
    resolution = resolutions.get(path)
    if resolution == "local":
        return local
    if resolution == "upstream":
        return upstream
    conflicts.append(path)
    return local


def plan_reviewed_upgrade(target: Path, source: Path, reviewed_base: dict, *, resolutions: dict[str, str] | None = None) -> dict:
    """Dry-run a deliberate upgrade using a caller-reviewed historical baseline.

    Unlike automatic provisioning this accepts a manually identified Git base.
    It never writes data. Competing edits need an explicit per-path decision.
    """
    local_raw = json.loads(target.read_text(encoding="utf-8"))
    upstream_raw = json.loads(source.read_text(encoding="utf-8"))
    documents = [_with_defaults(raw, WorkflowDef.from_dict(raw).to_dict())
                 for raw in (reviewed_base, local_raw, upstream_raw)]
    base, local, upstream = documents
    for document in documents:
        # Version counters/timestamps are editor metadata, not workflow behavior.
        for key in ("version", "created_at", "updated_at"):
            document.pop(key, None)
        # Older editors regenerated visual edge IDs. Match graph semantics so
        # the same edge is not retained twice during an explicit upgrade.
        for edge in document.get("edges", []):
            identity = json.dumps({key: value for key, value in edge.items() if key != "id"},
                                  sort_keys=True, ensure_ascii=False)
            edge["id"] = "edge-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    choices = {}
    old_nodes = {node["id"]: node for node in base.get("nodes", [])}
    for node in local.get("nodes", []):
        old = old_nodes.get(node["id"])
        if old and node.get("node_type", "agent") == "agent" and node.get("model_override", "") != old.get("model_override", ""):
            choices[node["id"]] = node.get("model_override", "")
            node["model_override"] = old.get("model_override", "")
    conflicts = []
    merged = _merge_reviewed(base, local, upstream, "", conflicts, resolutions or {})
    for key in ("version", "created_at", "updated_at"):
        if key in upstream_raw:
            merged[key] = upstream_raw[key]
    return {"definition": merged, "node_models": choices, "conflicts": conflicts,
            "target_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
            "source_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
            "preferences": read_model_preferences(target.parent)}


def apply_reviewed_upgrade(target: Path, source: Path, plan: dict) -> Path:
    """Apply one reviewed, conflict-free plan; reject stale input and keep backups."""
    if plan["conflicts"]:
        raise ValueError("Unresolved workflow upgrade conflicts: " + ", ".join(plan["conflicts"]))
    if (hashlib.sha256(target.read_bytes()).hexdigest() != plan["target_hash"]
            or hashlib.sha256(source.read_bytes()).hexdigest() != plan["source_hash"]
            or read_model_preferences(target.parent) != plan["preferences"]):
        raise ValueError("Workflow or model preferences changed after upgrade review")
    backup = target.parent / ".upgrade-backups" / uuid.uuid4().hex
    backup.mkdir(parents=True)
    for name in ("definition.json", ".extension.json", BASE_FILE, MODEL_PREFERENCES_FILE):
        original = target.parent / name
        if original.exists():
            shutil.copy2(original, backup / name)
    write_model_preferences(target.parent, {**plan["node_models"], **plan["preferences"]})
    atomic_write(target, json.dumps(plan["definition"], ensure_ascii=False, indent=2).encode("utf-8"))
    atomic_write(target.parent / BASE_FILE, source.read_bytes())
    marker_path = target.parent / ".extension.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker.setdefault("files", {})["definition.json"] = {
        "source_hash": plan["source_hash"], "installed_hash": plan["source_hash"],
    }
    marker["reviewed_upgrade"] = {"backup": backup.name, "previous_hash": plan["target_hash"]}
    marker.pop("conflicts", None)
    atomic_write(marker_path, json.dumps(marker, ensure_ascii=False, indent=2).encode("utf-8"))
    return backup
