"""Verify legacy short-story coverage from the original distillation archives."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verified_coverage(manifest, candidates, archive):
    windows = load(archive)
    digest = manifest["source_sha256"]
    source = windows["source"]
    if source.get("text_sha256") != digest or not candidates.get("covered_window_ids"):
        return None
    entries = windows["windows"]
    if [w["window_id"] for w in entries] != candidates["covered_window_ids"]:
        return None
    learning = archive.parents[1]
    snapshot = learning / "sources" / (digest + ".txt")
    if not snapshot.is_file():
        return None
    raw = snapshot.read_text(encoding="utf-8-sig")
    if hashlib.sha256(raw.encode()).hexdigest() != digest:
        return None
    end = 0
    for item in entries:
        start, stop = item["source_start"], item["source_end"]
        if not 0 <= start <= end < stop <= len(raw) or raw[start:stop] != item["text"]:
            return None
        end = stop
    if end != len(raw):
        return None
    metadata_path = learning / "dna" / "metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = load(metadata_path)
    units = metadata.get("source_units", [])
    if (metadata.get("source_mode") != "short_full" or metadata.get("source", {}).get("text_sha256") != digest
            or len(units) != 1):
        return None
    unit = units[0]
    start, stop = unit["source_start"], unit["source_end"]
    if not 0 <= start < stop <= end:
        return None
    return {"chapters": [{"id": "short-0001", "title": "短篇全文", "start": start, "end": stop}],
            "analyzed_chapters": ["short-0001"], "missing_chapters": [], "complete": True,
            "window_count": len(entries), "analyzed_window_count": len(entries),
            "completeness_basis": "archived_short_full"}


def run(library, jobs, backup=None):
    archives = {}
    for path in sorted(jobs.glob("*/learning/cache/windows.json")):
        source = load(path).get("source", {}).get("text_sha256")
        archives.setdefault(source, []).append(path)
    updates = []
    for path in sorted(library.glob("*/manifest.json")):
        manifest = load(path)
        if manifest.get("source_mode") != "short_full" or manifest.get("source_coverage"):
            continue
        candidates = load(path.with_name("candidates.json"))
        if candidates.get("source", {}).get("text_sha256") != manifest.get("source_sha256"):
            raise ValueError(f"{path.parent.name} 来源不一致")
        for archive in archives.get(manifest["source_sha256"], []):
            coverage = verified_coverage(manifest, candidates, archive)
            if coverage:
                updates.append((path, path.read_bytes(), {**manifest, "source_coverage": coverage}))
                break
        else:
            raise ValueError(f"{path.parent.name} 缺少可核实的全文记录")
    if updates and backup is not None:
        backup.mkdir(parents=True, exist_ok=False)
        for path, original, _ in updates:
            (backup / (path.parent.name + ".json")).write_bytes(original)
        for path, original, updated in updates:
            if path.read_bytes() != original:
                raise ValueError(f"{path.parent.name} 在迁移期间有变化")
            with NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as stream:
                json.dump(updated, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            temporary = Path(stream.name)
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return [path.parent.name for path, _, _ in updates]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--apply-with-backup", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.library, args.jobs, args.apply_with_backup), ensure_ascii=False))
