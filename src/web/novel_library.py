"""Writing-library upgrades and per-book usage, separate from adopted blueprints."""
from pathlib import Path
import hashlib
import json
from .novel_reference_choices import with_reference_choices


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return fallback


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def enrich_candidates(old, new):
    """Keep existing IDs and decisions usable when a source is analyzed again."""
    merged = dict(new)
    candidates = [{**item, "source": item.get("source") or old.get("source", {})} for item in old.get("candidates", [])]
    for item in new.get("candidates", []):
        if not any(item.get("candidate_id") == before.get("candidate_id") or item.get("mechanism") == before.get("mechanism") for before in candidates):
            candidates.append({**item, "source": item.get("source") or new.get("source", {})})
    merged["sources"] = []
    for data in (old, new):
        for source in [data.get("source", {}), *data.get("sources", [])]:
            if source and source not in merged["sources"]:
                merged["sources"].append(source)
    merged["candidates"] = candidates
    merged["candidates_sha256"] = fingerprint(candidates)
    for key in ("style_observations", "conflict_patterns"):
        items = [{**item, "source": item.get("source") or old.get("source", {})} for item in old.get(key, [])]
        for raw in new.get(key, []):
            item = {**raw, "source": raw.get("source") or new.get("source", {})}
            if item not in items:
                items.append(item)
        merged[key] = items
    return with_reference_choices(merged)


def adopted_writing(root: Path):
    active_file = root / "learning/active.json"
    if not active_file.exists():
        return {"version": 0, "selected_candidate_ids": [], "mechanisms": [], "sources": [], "selected_style_ids": [], "selected_conflict_ids": [], "styles": [], "conflicts": []}
    active = read_json(active_file, {})
    relative = active.get("blueprint_path", "")
    target = (root / relative).resolve()
    blueprint = read_json(target, {}) if relative and target.is_relative_to(root.resolve()) else {}
    if not blueprint or active.get("blueprint_sha256") != fingerprint(blueprint):
        raise ValueError("已采用写法的记录校验失败，请修复记录后再确认新增写法")
    return {"selected_style_ids": [], "selected_conflict_ids": [], "styles": [], "conflicts": [], **blueprint, "version": active.get("version", 0)}


def usage(root: Path, folder: Path):
    reference = with_reference_choices(read_json(folder / "candidates.json", {}))
    current = with_reference_choices(read_json(root / "learning/candidates.json", {}))
    references = read_json(root / "learning/library_refs.json", {})
    source = reference.get("source", {}).get("text_sha256")
    attached = folder.name in references.get("items", []) and bool(source)
    if not attached:
        return {"status": "available", "selected_count": 0, "style_count": 0, "conflict_count": 0, "selected_candidate_ids": [], "selected_style_ids": [], "selected_conflict_ids": []}
    try:
        blueprint = adopted_writing(root)
    except ValueError:
        return {"status": "attached", "selected_count": 0, "error": "已采用写法记录校验失败"}
    # A selected checkbox is not adoption. The authoritative completed blueprint
    # must still match its receipt and the reference source.
    sources = [blueprint.get("source", {}), *blueprint.get("sources", [])]
    valid = any(item.get("text_sha256") == source for item in sources)
    ids = {item.get("candidate_id") for item in reference.get("candidates", [])}
    selected = sum(item in ids for item in blueprint.get("selected_candidate_ids", [])) if valid else 0
    result = {"status": "adopted" if selected else "attached", "selected_count": selected,
              "selected_candidate_ids": [item for item in blueprint.get("selected_candidate_ids", []) if item in ids] if valid else []}
    for kind in ("style", "conflict"):
        identifiers = {item["choice_id"] for item in reference[kind + "_choices"]}
        selected_ids = [item for item in blueprint.get("selected_" + kind + "_ids", []) if item in identifiers] if valid else []
        result["selected_" + kind + "_ids"] = selected_ids
        result[kind + "_count"] = len(selected_ids)
        if selected_ids:
            result["status"] = "adopted"
        if identifiers - {item["choice_id"] for item in current[kind + "_choices"]}:
            result["update_available"] = True
    if any(not any(item.get("candidate_id") == before.get("candidate_id") or
                   (item.get("mechanism") and item.get("mechanism") == before.get("mechanism"))
                   for before in current.get("candidates", [])) for item in reference.get("candidates", [])):
        result["update_available"] = True
    return result


def profile_from_workspace(root):
    structured = read_json(root / "learning/dna/profile.json", {})
    file = root / "learning/reference_profile.md"
    markdown = file.read_text(encoding="utf-8-sig") if file.is_file() else ""
    return {**structured, "markdown": markdown}
