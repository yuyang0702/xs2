"""Persist novel project state independently of a browser and expose workspace text."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.config import DATA_DIR, WORKFLOW_WORKSPACES_DIR
from .workflow_access import _ensure_http_mutation_allowed, _ensure_workflow_writable

router = APIRouter(prefix="/api/novel-console", tags=["novel-console"])
_lock = threading.RLock()
_index = DATA_DIR / "novel-console" / "workspaces.json"
_manifest = ".novel-project.json"


def safe_target(root: Path, relative: str) -> Path:
    root = root.resolve()
    if Path(relative).is_absolute() or re.match(r"^[a-zA-Z]:", relative):
        raise HTTPException(403, "请使用工作区内的相对路径")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise HTTPException(403, "路径不在工作区内")
    return target


def atomic_json(target: Path, value: object) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".novel-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def known_workspaces() -> list[Path]:
    roots = list(WORKFLOW_WORKSPACES_DIR.glob("*"))
    if _index.is_file():
        roots.extend(Path(item) for item in json.loads(_index.read_text(encoding="utf-8")))
    return sorted({root.resolve() for root in roots if root.is_dir()}, key=str)


@router.get("/projects")
async def list_projects():
    projects = []
    with _lock:
        for root in known_workspaces():
            path = root / _manifest
            if path.is_file():
                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
            elif (root / "story").is_dir() or root.name == "xs2-novel-workbench":
                state = {"title": root.name, "mode": "serial" if len(list((root / "story").glob("*/chapter.md"))) > 1 else "short"}
            else:
                continue
            projects.append({"workspace": str(root), "state": state})
    return {"projects": projects}


class ProjectSave(BaseModel):
    workflow_id: str
    workspace: str
    state: dict


@router.put("/projects")
async def save_project(payload: ProjectSave, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    if len(json.dumps(payload.state)) > 500_000:
        raise HTTPException(413, "作品设置过大")
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    with _lock:
        atomic_json(safe_target(root, _manifest), payload.state)
        roots = {str(item) for item in known_workspaces()}
        roots.add(str(root))
        atomic_json(_index, sorted(roots))
    return {"success": True, "workspace": str(root)}


class TextWrite(BaseModel):
    workflow_id: str
    workspace: str
    path: str
    content: str = Field(max_length=2_000_000)


@router.put("/text")
async def write_text(payload: TextWrite, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    target = safe_target(root, payload.path)
    # Only author-provided references and confirmed console plans are writable here.
    if not payload.path.replace("\\", "/").startswith(("references/", "meta/console-")):
        raise HTTPException(403, "此接口只写入参考资料和已确认的创作计划")
    with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload.content, encoding="utf-8")
    return {"success": True, "path": payload.path, "sha256": hashlib.sha256(payload.content.encode()).hexdigest()}
