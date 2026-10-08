"""Persist novel project state independently of a browser and expose workspace text."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import tempfile
import threading
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import UUID
from typing import Literal

import httpx

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.config import DATA_DIR, WORKFLOW_WORKSPACES_DIR
from .workflow_access import _ensure_http_mutation_allowed, _ensure_workflow_writable, _get_manager
from .novel_assistant import NovelAssistantJobs
from .novel_library import adopted_writing, enrich_candidates, fingerprint, profile_from_workspace, usage
from .novel_reference_choices import with_reference_choices
from .novel_progress import progress
from .novel_repair import repair_context, prepare_repair, ensure_idle
from .novel_story_support import story_support
from .novel_workflow_models import novel_definition, model_settings, save_model_settings

router = APIRouter(prefix="/api/novel-console", tags=["novel-console"])
_lock = threading.RLock()
_index = DATA_DIR / "novel-console" / "workspaces.json"
_manifest = ".novel-project.json"
_library_root = DATA_DIR / "writing-library"
_FANQIE_HOSTS = {"fanqienovel.com", "www.fanqienovel.com"}


class NovelModelSave(BaseModel):
    workflow_id: str
    expected_digest: str = Field(min_length=64, max_length=64)
    node_models: dict[str, str]


@router.get("/workflow-models")
def novel_workflow_models(workflow_id: str, request: Request):
    from src.core.model_manager import get_model_manager
    return model_settings(novel_definition(_get_manager(request), workflow_id), get_model_manager())


@router.patch("/workflow-models")
def update_novel_workflow_models(payload: NovelModelSave, request: Request):
    from src.core.model_manager import get_model_manager
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    manager = _ensure_workflow_writable(request, payload.workflow_id)
    with _lock:
        return save_model_settings(manager, payload.workflow_id, payload.expected_digest,
                                   payload.node_models, get_model_manager())


class _PublicPageParser(HTMLParser):
    """Small, dependency-free parser for public reading pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._in_title = False
        self._skip_depth = 0
        self._anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"}:
            self._skip_depth += 1
        if tag == "a" and self._skip_depth == 0:
            href = values.get("href") or ""
            if href:
                self._anchor = {"href": href, "text": ""}
        if tag in {"p", "div", "br", "h1", "h2", "h3", "h4", "li"} and self._skip_depth == 0:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "a" and self._anchor is not None:
            self.links.append(self._anchor)
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.text_parts.append(text)
        if self._anchor is not None:
            self._anchor["text"] = f"{self._anchor['text']} {text}".strip()


class _FanqiePageParser(HTMLParser):
    """Parse the server-rendered parts of 番茄's book and reader pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.book_title_parts: list[str] = []
        self.chapter_title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._skip_depth = 0
        self._content_depth = 0
        self._chapter_list_depth = 0
        self._title_depth = 0
        self._book_title_depth = 0
        self._chapter_title_depth = 0
        self._anchor: dict[str, str] | None = None
        self._class_stack: list[tuple[str, bool, bool, bool, bool]] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        return set((dict(attrs).get("class") or "").split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        classes = self._classes(attrs)
        if tag == "title":
            self._title_depth += 1
        if "muye-reader-content" in classes:
            self._content_depth += 1
        is_chapter_list = bool({"chapter-list", "chapter"} & classes)
        if is_chapter_list:
            self._chapter_list_depth += 1
        is_book_title = "book-title" in classes or (tag == "h1" and "muye-reader-title" not in classes and self._content_depth == 0)
        if is_book_title:
            self._book_title_depth += 1
        if "muye-reader-title" in classes:
            self._chapter_title_depth += 1
        self._class_stack.append((tag, "muye-reader-content" in classes, is_chapter_list, is_book_title, "muye-reader-title" in classes))
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"}:
            self._skip_depth += 1
        if tag == "a" and self._skip_depth == 0:
            values = dict(attrs)
            anchor_classes = set((values.get("class") or "").split())
            href = values.get("href") or ""
            if "chapter-item-title" not in anchor_classes:
                href = ""
            if href:
                self._anchor = {"href": href, "text": ""}
        if self._content_depth > 0 and self._skip_depth == 0 and tag in {"p", "div", "br"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "a" and self._anchor is not None:
            self.links.append(self._anchor)
            self._anchor = None
        for index in range(len(self._class_stack) - 1, -1, -1):
            opened, content, chapter_list, book_title, chapter_title = self._class_stack[index]
            if opened != tag:
                continue
            self._class_stack.pop(index)
            if content:
                self._content_depth = max(0, self._content_depth - 1)
            if chapter_list:
                self._chapter_list_depth = max(0, self._chapter_list_depth - 1)
            if book_title:
                self._book_title_depth = max(0, self._book_title_depth - 1)
            if chapter_title:
                self._chapter_title_depth = max(0, self._chapter_title_depth - 1)
            break

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text or self._skip_depth:
            return
        if self._title_depth:
            self.title_parts.append(text)
        if self._book_title_depth:
            self.book_title_parts.append(text)
        if self._chapter_title_depth:
            self.chapter_title_parts.append(text)
        if self._content_depth:
            self.text_parts.append(text)
        if self._anchor is not None:
            self._anchor["text"] = f"{self._anchor['text']} {text}".strip()


def _validate_public_url(raw: str) -> str:
    parsed = urlparse(raw.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "只支持公开的 http/https 网址")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "网址端口无效") from exc
    if parsed.username or parsed.password or port not in {None, 80, 443}:
        raise HTTPException(400, "网址不能包含登录信息或非标准端口")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise HTTPException(403, "不允许访问本机地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise HTTPException(400, "网址域名无法解析") from exc
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(403, "不允许访问内网或保留地址")
    return parsed.geturl()


def _validate_fanqie_url(raw: str) -> str:
    """Validate a public 番茄 URL without accepting another site's content."""
    parsed = urlparse(raw.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _FANQIE_HOSTS:
        raise HTTPException(400, "目前只支持番茄小说 fanqienovel.com 的公开作品网址")
    # The allowlist above fixes the destination to 番茄.  Some development
    # environments resolve public domains through a private DNS test address;
    # retain the normal URL checks while allowing that specific, fixed host.
    try:
        checked = _validate_public_url(raw)
    except HTTPException as exc:
        if exc.status_code != 403 or exc.detail != "不允许访问内网或保留地址":
            raise
        checked = parsed.geturl()
        parsed = urlparse(checked)
    if not re.match(r"^/(?:page|reader)(?:/|$)", parsed.path):
        raise HTTPException(400, "请粘贴番茄小说作品详情页、目录页或正文页网址")
    return checked


async def _fetch_public_page(url: str) -> tuple[str, str]:
    checked = _validate_fanqie_url(url)
    headers = {"User-Agent": "XS2-Novel-Importer/1.0 (+public-page-import)"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=False, headers=headers) as client:
            response = await client.get(checked)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise HTTPException(400, "网页重定向地址为空")
                redirected = _validate_fanqie_url(urljoin(checked, location))
                response = await client.get(redirected)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(400, f"网页返回 HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(400, "网页暂时无法访问") from exc
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and not response.text.lstrip().startswith(("<!doctype", "<html", "<HTML")):
        raise HTTPException(400, "网址不是可解析的公开 HTML 页面")
    if len(response.content) > 8_000_000:
        raise HTTPException(413, "网页内容超过 8MB 上限")
    return str(response.url), response.text


def _parse_public_page(url: str, html: str) -> dict[str, object]:
    parser = _FanqiePageParser()
    parser.feed(html)
    title = " ".join(parser.chapter_title_parts or parser.book_title_parts or parser.title_parts).strip()
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(parser.text_parts)).strip()
    chapters: list[dict[str, object]] = []
    seen: set[str] = set()
    chapter_pattern = re.compile(r"(?:第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回卷]|chapter\s*[-_ ]?\d+)", re.I)
    for link in parser.links:
        target = urljoin(url, link["href"])
        try:
            target = _validate_fanqie_url(target)
        except HTTPException:
            continue
        parsed = urlparse(target)
        if target in seen or not parsed.path.startswith("/reader/"):
            continue
        label = re.sub(r"\s+", " ", link.get("text", "")).strip()
        if not label or not chapter_pattern.search(label + " " + parsed.path):
            continue
        # The detail page also exposes a "最近更新" link with the same
        # anchor class.  It points to a chapter but is not a directory item.
        if not re.match(r"^(?:第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回卷]|番外|chapter\s*[-_ ]?\d+)", label, re.I):
            continue
        seen.add(target)
        chapters.append({"index": len(chapters) + 1, "title": label[:160], "url": target, "selected": len(chapters) < 20})
        if len(chapters) >= 200:
            break
    private_use = sum(1 for char in text if 0xE000 <= ord(char) <= 0xF8FF)
    return {"title": title[:200], "text": text, "chapters": chapters, "font_obfuscated": private_use > 0}


def _fanqie_warnings(pages: list[dict[str, object]]) -> list[str]:
    if any(page.get("font_obfuscated") for page in pages):
        return ["部分番茄章节使用了网页字体混淆，当前只保留公开页面原文；若导入文本出现不可读字符，请使用番茄官方导出或本地 TXT/Markdown 文件。"]
    return []


def safe_target(root: Path, relative: str) -> Path:
    root = root.resolve()
    if Path(relative).is_absolute() or re.match(r"^[a-zA-Z]:", relative):
        raise HTTPException(403, "请使用工作区内的相对路径")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise HTTPException(403, "路径不在工作区内")
    return target


def safe_library_id(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw.strip()).strip("-").lower()
    if not value:
        raise HTTPException(400, "写法库条目名称不能为空")
    return value[:80]


def library_path(item_id: str) -> Path:
    value = safe_library_id(item_id)
    target = (_library_root / value).resolve()
    if not target.is_relative_to(_library_root.resolve()):
        raise HTTPException(403, "写法库路径无效")
    return target


def read_json_file(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback
    except (OSError, ValueError):
        return fallback


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
    # Books are isolated below data/workspaces/books/<slug>; include nested
    # workspaces so the works switcher sees newly created books immediately.
    roots = [item for item in WORKFLOW_WORKSPACES_DIR.rglob("*") if item.is_dir()]
    if _index.is_file():
        roots.extend(Path(item) for item in json.loads(_index.read_text(encoding="utf-8")))
    return sorted({root.resolve() for root in roots if root.is_dir()}, key=str)


@router.get("/projects")
async def list_projects():
    projects = []
    with _lock:
        for root in known_workspaces():
            if root.is_relative_to((WORKFLOW_WORKSPACES_DIR / "reference-jobs").resolve()):
                continue
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
            projects.append({"workspace": str(root), "state": state,
                             "progress": progress(root, state, DATA_DIR / "workflows")})
    return {"projects": projects}


@router.get("/progress")
async def get_novel_progress(request: Request, workflow_id: str, workspace: str):
    manager = _get_manager(request)
    root = manager._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    state = read_json_file(root / _manifest, {})
    return progress(root, state, DATA_DIR / "workflows")


class UrlInspect(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/import-url/inspect")
async def inspect_import_url(payload: UrlInspect):
    """读取公开页面的目录，不登录、不绕过验证码或访问控制。"""
    final_url, html = await _fetch_public_page(payload.url)
    parsed = _parse_public_page(final_url, html)
    return {
        "url": final_url,
        "title": parsed["title"],
        "detected_type": "serial_chapters" if parsed["chapters"] else "short_full",
        "chapters": parsed["chapters"],
        "has_page_text": bool(parsed["text"]),
        "warnings": _fanqie_warnings([parsed]),
    }


class UrlChapter(BaseModel):
    index: int = Field(ge=1, le=200)
    title: str = Field(default="", max_length=200)
    url: str = Field(min_length=8, max_length=2000)


class UrlImport(BaseModel):
    workflow_id: str
    workspace: str
    url: str = Field(min_length=8, max_length=2000)
    source_mode: str = "auto"
    chapters: list[UrlChapter] = Field(default_factory=list, max_length=200)


@router.post("/import-url/fetch")
async def import_url(payload: UrlImport, request: Request):
    """抓取用户确认的公开页面并写入当前作品 references。"""
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    if payload.source_mode not in {"auto", "short_full", "serial_chapters"}:
        raise HTTPException(400, "参考语料类型无效")
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    source_url = _validate_fanqie_url(payload.url)
    selected = payload.chapters[:200]
    pages: list[dict[str, object]] = []
    if selected:
        for chapter in selected:
            chapter_url = _validate_fanqie_url(urljoin(source_url, chapter.url))
            if urlparse(chapter_url).netloc.lower() != urlparse(source_url).netloc.lower():
                raise HTTPException(400, "章节链接必须来自同一公开站点")
            final_url, html = await _fetch_public_page(chapter_url)
            parsed = _parse_public_page(final_url, html)
            if not parsed["text"]:
                continue
            pages.append({"index": chapter.index, "title": chapter.title or parsed["title"], "url": final_url, "text": parsed["text"], "font_obfuscated": parsed.get("font_obfuscated", False)})
    else:
        final_url, html = await _fetch_public_page(source_url)
        parsed = _parse_public_page(final_url, html)
        if not parsed["text"]:
            raise HTTPException(400, "网页中没有可读取的正文文本")
        pages.append({"index": 1, "title": parsed["title"] or "网页正文", "url": final_url, "text": parsed["text"], "font_obfuscated": parsed.get("font_obfuscated", False)})
    if not pages:
        raise HTTPException(400, "没有抓取到可用章节正文")
    content = "\n\n".join(f"===== SOURCE CHAPTER {page['index']}: {page['title']} =====\n\n{page['text']}" for page in pages)
    if len(content) > 10_000_000:
        raise HTTPException(413, "选中的章节内容超过 10MB 上限，请减少章节数量")
    corpus_path = safe_target(root, "references/url-imported-corpus.txt")
    manifest_path = safe_target(root, "references/url-import.json")
    warnings = _fanqie_warnings(pages)
    manifest = {"source_url": source_url, "source_mode": payload.source_mode, "chapters": [{key: page[key] for key in ("index", "title", "url")} for page in pages], "imported_at": datetime.now(timezone.utc).isoformat(), "characters": len(content), "warnings": warnings}
    with _lock:
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        corpus_path.write_text(content, encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"success": True, "path": "references/url-imported-corpus.txt", "manifest_path": "references/url-import.json", "title": pages[0]["title"], "chapter_count": len(pages), "characters": len(content), "warnings": warnings}


@router.get("/library")
async def list_writing_library():
    """列出跨作品可复用的写法蒸馏结果。"""
    _library_root.mkdir(parents=True, exist_ok=True)
    items = []
    for folder in sorted(_library_root.iterdir(), key=lambda item: item.name) if _library_root.exists() else []:
        if not folder.is_dir():
            continue
        manifest = read_json_file(folder / "manifest.json", {})
        if not isinstance(manifest, dict):
            continue
        choices = with_reference_choices(read_json_file(folder / "candidates.json", {}))
        items.append({**manifest, "style_count": len(choices["style_choices"]), "conflict_count": len(choices["conflict_choices"])})
    return {"items": items}


@router.get("/library/{library_id}")
async def get_writing_library_item(library_id: str):
    folder = library_path(library_id)
    manifest = read_json_file(folder / "manifest.json", None)
    if not isinstance(manifest, dict):
        raise HTTPException(404, "写法库条目不存在")
    return {
        "manifest": manifest,
        "profile": read_json_file(folder / "profile.json", {}),
        "candidates": with_reference_choices(read_json_file(folder / "candidates.json", {"candidates": []})),
    }


@router.get("/library-usage")
async def get_library_usage(request: Request, workflow_id: str, workspace: str):
    manager = _get_manager(request)
    root = manager._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    return {"items": {folder.name: usage(root, folder) for folder in _library_root.iterdir()
                      if folder.is_dir() and (folder / "manifest.json").is_file()} if _library_root.exists() else {}}


@router.get("/adopted-writing")
async def get_adopted_writing(request: Request, workflow_id: str, workspace: str):
    manager = _get_manager(request)
    root = manager._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    try:
        return adopted_writing(root)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/reference-candidates")
async def get_reference_candidates(request: Request, workflow_id: str, workspace: str):
    manager = _get_manager(request)
    root = manager._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    data = read_json_file(root / "learning/candidates.json", None)
    if not isinstance(data, dict):
        return {"candidates": [], "style_observations": [], "conflict_patterns": [], **with_reference_choices({})}
    return with_reference_choices(data)


@router.api_route("/export/download", methods=["GET", "HEAD"])
async def download_novel_manuscript(request: Request, workflow_id: str, workspace: str, filename: str = "小说成品.md"):
    """Download the actual exported manuscript without browser-specific Blob URLs."""
    manager = _get_manager(request)
    root = manager._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    target = safe_target(root, "export/manuscript.md")
    if not target.is_file():
        raise HTTPException(404, "本书尚未生成成品，请先完成导出步骤")
    download_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)[:160].strip() or "小说成品.md"
    if not download_name.lower().endswith(".md"):
        download_name += ".md"
    return FileResponse(target, media_type="text/markdown; charset=utf-8", filename=download_name)


class LibraryPublish(BaseModel):
    workflow_id: str
    workspace: str
    name: str = Field(min_length=1, max_length=120)
    genres: list[str] = Field(default_factory=list, max_length=16)
    pov: list[str] = Field(default_factory=list, max_length=4)
    tone: list[str] = Field(default_factory=list, max_length=16)
    language: str = "中文"


@router.post("/library/publish")
async def publish_writing_library(payload: LibraryPublish, request: Request):
    """把当前书工作区中已校验的蒸馏结果保存为可复用的库条目。"""
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    candidates_path = safe_target(root, "learning/candidates.json")
    if not candidates_path.is_file():
        raise HTTPException(400, "当前工作区还没有完成蒸馏，找不到 learning/candidates.json")
    candidates = read_json_file(candidates_path, None)
    if not isinstance(candidates, dict) or not isinstance(candidates.get("candidates"), list):
        raise HTTPException(400, "蒸馏候选文件格式无效")
    candidates = with_reference_choices(candidates)
    source_sha256 = candidates.get("source", {}).get("text_sha256") if isinstance(candidates.get("source"), dict) else None
    new_profile = profile_from_workspace(root)
    if new_profile.get("source_sha256") and new_profile["source_sha256"] != source_sha256:
        raise HTTPException(400, "风格分析与候选来源不一致，请完成本次蒸馏后再保存")
    with _lock:
        existing_folder = None
        for item in _library_root.iterdir() if _library_root.exists() else []:
            manifest = read_json_file(item / "manifest.json", {}) if item.is_dir() else {}
            if source_sha256 and manifest.get("source_sha256") == source_sha256:
                existing_folder = item
                break
        if existing_folder:
            folder = existing_folder
            manifest = read_json_file(folder / "manifest.json", {})
            old = read_json_file(folder / "candidates.json", {})
            old_profile = read_json_file(folder / "profile.json", {})
            candidates = enrich_candidates(old, candidates)
            profile = new_profile if new_profile.get("markdown", "").strip() else old_profile
            changed = fingerprint(old) != fingerprint(candidates) or fingerprint(old_profile) != fingerprint(profile)
            if changed:
                manifest.update(version=manifest.get("version", 1) + 1,
                                updated_at=datetime.now(timezone.utc).isoformat())
        else:
            item_id = safe_library_id(payload.name)
            folder = library_path(item_id)
            if folder.exists():
                item_id += "-" + hashlib.sha256(datetime.now(timezone.utc).isoformat().encode()).hexdigest()[:8]
                folder = library_path(item_id)
            folder.mkdir(parents=True, exist_ok=False)
            profile = new_profile
            manifest = {"id": item_id, "name": payload.name.strip(),
                        "genres": [str(item).strip() for item in payload.genres if str(item).strip()],
                        "pov": [str(item).strip() for item in payload.pov if str(item).strip()],
                        "tone": [str(item).strip() for item in payload.tone if str(item).strip()],
                        "language": payload.language.strip() or "中文", "source_sha256": source_sha256,
                        "created_at": datetime.now(timezone.utc).isoformat(), "version": 1}
        manifest.update(candidate_count=len(candidates["candidates"]),
                        conflict_count=len(candidates.get("conflict_patterns", [])),
                        has_style_profile=bool(profile.get("markdown", "").strip()),
                        source_mode=profile.get("source_mode", "auto"))
        atomic_json(folder / "candidates.json", candidates)
        atomic_json(folder / "profile.json", profile)
        atomic_json(folder / "manifest.json", manifest)
    return {"item": manifest}



class LibraryAttach(BaseModel):
    workflow_id: str
    workspace: str
    library_id: str
    refresh: bool = False


@router.post("/library/attach")
async def attach_writing_library(payload: LibraryAttach, request: Request):
    """把库条目的候选复制到本书，仍由本书单独选择采用哪些规则。"""
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    folder = library_path(payload.library_id)
    candidates_path = folder / "candidates.json"
    if not candidates_path.is_file():
        raise HTTPException(404, "写法库候选不存在")
    candidates = read_json_file(candidates_path, None)
    if not isinstance(candidates, dict):
        raise HTTPException(400, "写法库候选格式无效")
    candidates = with_reference_choices(candidates)
    with _lock:
        current_usage = usage(root, folder)
        if current_usage["status"] != "available" and not (payload.refresh and current_usage.get("update_available")):
            return {"library_id": payload.library_id, "candidates": candidates,
                    "already_attached": True, "usage": current_usage}
        target = safe_target(root, "learning/candidates.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            candidates = enrich_candidates(read_json_file(target, {}), candidates)
        atomic_json(target, candidates)
        # Style is source analysis for the adviser; it never replaces the book's
        # meta/style_profile.md or automatically becomes a generation instruction.
        profile = read_json_file(folder / "profile.json", {})
        atomic_json(safe_target(root, "learning/reference_style.json"), profile)
        safe_target(root, "learning/reference_profile.md").write_text(profile.get("markdown", ""), encoding="utf-8")
        refs = safe_target(root, "learning/library_refs.json")
        refs_data = read_json_file(refs, {"items": []})
        if not isinstance(refs_data, dict):
            refs_data = {"items": []}
        refs_data["items"] = list(dict.fromkeys([*refs_data.get("items", []), payload.library_id]))
        refs_data["active_library_id"] = payload.library_id
        atomic_json(refs, refs_data)
    return {"library_id": payload.library_id, "candidates": candidates,
            "already_attached": False, "usage": usage(root, folder)}



class ProjectSave(BaseModel):
    workflow_id: str
    workspace: str
    state: dict


class NovelAssistantRequest(BaseModel):
    """Context sent by the novel workbench to the model-backed writing adviser."""

    question: str = Field(min_length=1, max_length=12000)
    workflow_id: str
    workspace: str
    request_id: UUID
    project: dict = Field(default_factory=dict)
    stage: str = ""
    next_stage: str = ""
    missing: list[str] = Field(default_factory=list, max_length=32)
    candidates: list[dict] = Field(default_factory=list, max_length=80)
    conflict_plan: dict = Field(default_factory=dict)
    purpose: Literal['general', 'reader_repair', 'configure', 'advisor', 'plot'] = 'general'
    chapter: str = Field(default='', max_length=4)
    scope: Literal['book', 'volume', 'chapter'] = 'chapter'


def _assistant_jobs(request: Request) -> NovelAssistantJobs:
    jobs = getattr(request.app.state, "novel_assistant_jobs", None)
    if jobs is None:
        jobs = NovelAssistantJobs()
        request.app.state.novel_assistant_jobs = jobs
    return jobs


@router.get("/assistant/history")
async def novel_assistant_history(workflow_id: str, workspace: str, request: Request):
    mgr = request.app.state.workflow_manager
    root = mgr._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    return {"entries": _assistant_jobs(request).history(root)}


@router.post("/assistant")
async def novel_assistant(payload: NovelAssistantRequest, request: Request):
    """Submit a durable analysis without tying model execution to a browser tab."""
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    data = payload.model_dump(mode="json")
    if payload.purpose == 'advisor':
        from src.core.model_manager import get_model_manager
        settings = model_settings(novel_definition(mgr, "xs2-novel-flywheel-novel-advisor"), get_model_manager())
        nodes = settings['nodes']
        if len(nodes) != 1 or not nodes[0]['available']:
            raise HTTPException(409, "小说顾问尚未配置可用模型，请在当前步骤的模型设置中选择。")
        data['_model_override'] = nodes[0]['effective_model']
    if payload.purpose == 'reader_repair':
        try:
            data['_repair_context'] = repair_context(root, payload.chapter, DATA_DIR / 'workflows')
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(409, str(error)) from error
    entry = _assistant_jobs(request).start(root, str(payload.request_id), data)
    return {"success": True, "entry": entry}


class PlotApply(BaseModel):
    workflow_id: str
    workspace: str
    entry_id: UUID
    option_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')


@router.post('/plot/apply')
async def apply_plot_proposal(payload: PlotApply, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    with _lock:
        jobs = _assistant_jobs(request)
        entries = jobs.history(root)
        entry = next((e for e in entries if e['id'] == str(payload.entry_id)), None)
        if not entry:
            raise HTTPException(404, '方案不存在，请重新讨论。')
        try:
            ensure_idle(root, DATA_DIR / 'workflows')
            result = story_support(required=True).apply_plan(root, entry, payload.option_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        entry.setdefault('plot_receipts', {})[payload.option_id] = result
        jobs._write(root, entries)
        return result


@router.get('/continuation')
async def continuation_check(request: Request, workflow_id: str, workspace: str, chapter: str):
    mgr = _get_manager(request)
    root = mgr._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    try:
        return story_support(required=True).preflight(root, chapter)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get('/archive-state')
async def novel_archive_state(request: Request, workflow_id: str, workspace: str):
    mgr = _get_manager(request)
    root = mgr._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    support = story_support()
    if not support:
        return {'message': '动态档案模块尚未加载', 'updated_chapter': '', 'items': []}
    states, _ = support.confirmed(root)
    latest = states[-1] if states else {}
    status = support.archive_status(root)
    items = []
    if states:
        for path, label, group, value in (
            ('meta/current_characters.md', '人物当前状态', '人物与关系', {'人物状态': latest.get('characters', []), '本章变化': latest.get('character_changes', {})}),
            ('meta/current_world.md', '世界当前局势', '世界设定', latest.get('world', {})),
            ('meta/story_timeline.md', '剧情变化记录', '连续性', [{'chapter': s['chapter'], '变化': s.get('story_changes', {})} for s in states]),
        ):
            items.append({'path': path, 'label': label, 'group': group,
                          'content': json.dumps({'档案进度': status['message'], **value} if isinstance(value, dict)
                                                else {'档案进度': status['message'], label: value}, ensure_ascii=False)})
    return {**status, 'items': items}


class RepairApply(BaseModel):
    workflow_id: str
    workspace: str
    entry_id: UUID
    plan: str = Field(min_length=1, max_length=24000)


@router.get('/reader-report')
async def chapter_reader_report(request: Request, workflow_id: str, workspace: str, chapter: str):
    mgr = _get_manager(request)
    root = mgr._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    try:
        context = repair_context(root, chapter, DATA_DIR / 'workflows')
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(409, str(error)) from error
    return {'report': context['report'], 'chapter': chapter}


@router.post('/repair/apply')
async def apply_repair_plan(payload: RepairApply, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    jobs = _assistant_jobs(request)
    with _lock:
        entries = jobs.history(root)
        entry = next((item for item in entries if item['id'] == str(payload.entry_id)), None)
        if not entry:
            raise HTTPException(404, '返修方案不存在，请重新分析。')
        try:
            ensure_idle(root, DATA_DIR / 'workflows')
            result = prepare_repair(root, entry, payload.plan)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not result['already_applied']:
            entry.update(applied_at=datetime.now(timezone.utc).isoformat(), feedback_path=result['feedback_path'], applied_plan=payload.plan)
            jobs._write(root, entries)
        from src.core.model_manager import get_model_manager
        return {**result, 'chapter': entry['chapter'], 'model_id': get_model_manager().get_default_model()}


@router.put("/projects")
async def save_project(payload: ProjectSave, request: Request):
    _ensure_http_mutation_allowed(request, payload.workflow_id)
    mgr = _ensure_workflow_writable(request, payload.workflow_id)
    if len(json.dumps(payload.state)) > 500_000:
        raise HTTPException(413, "作品设置过大")
    root = mgr._ws_manager.resolve_workflow_workspace(payload.workflow_id, override=payload.workspace).resolve()
    with _lock:
        manifest = safe_target(root, _manifest)
        incoming = dict(payload.state)
        existing = read_json_file(manifest, {})
        # Reject stale browser snapshots rather than silently replacing newer
        # workflow progress, settings or intentional writing-library changes.
        revision = existing.get("_revision", 0) if isinstance(existing, dict) else 0
        if incoming.get("_revision", 0) != revision:
            raise HTTPException(409, "作品已在后台或其他页面更新，请刷新作品后再保存")
        incoming["_revision"] = revision + 1
        atomic_json(manifest, incoming)
        roots = {str(item) for item in known_workspaces()}
        roots.add(str(root))
        atomic_json(_index, sorted(roots))
    return {"success": True, "workspace": str(root), "revision": incoming["_revision"]}


@router.delete("/projects")
async def delete_project(workflow_id: str, workspace: str, request: Request):
    """删除作品登记并物理移除对应的独立作品工作区。"""
    _ensure_http_mutation_allowed(request, workflow_id)
    mgr = _ensure_workflow_writable(request, workflow_id)
    root = mgr._ws_manager.resolve_workflow_workspace(workflow_id, override=workspace).resolve()
    books_root = (WORKFLOW_WORKSPACES_DIR / "books").resolve()
    workflow_root = WORKFLOW_WORKSPACES_DIR.resolve()
    if not root.is_relative_to(workflow_root) or root == workflow_root or root == books_root:
        raise HTTPException(403, "只能删除 data/workspaces 下的作品目录")

    # 不允许在工作流仍写入该目录时删除，避免运行中的任务继续写入已删除的作品。
    try:
        active_tasks = mgr.list_all_tasks(page=1, page_size=2000).get("tasks", [])
    except Exception:
        active_tasks = []
    active_statuses = {"pending", "pre_running", "running", "retry_waiting", "resume_pending"}
    for task in active_tasks:
        if task.get("status") not in active_statuses:
            continue
        task_workspace = task.get("workspace_override")
        if not task_workspace:
            continue
        try:
            task_root = mgr._ws_manager.resolve_workflow_workspace(
                task.get("workflow_id") or workflow_id, override=task_workspace
            ).resolve()
        except Exception:
            continue
        if task_root == root:
            raise HTTPException(409, "作品仍有工作流正在运行，请等待完成或先停止任务")

    with _lock:
        if root.exists():
            if not root.is_dir():
                raise HTTPException(400, "作品工作区不是目录，无法删除")
            shutil.rmtree(root)
        indexed = read_json_file(_index, [])
        if isinstance(indexed, list):
            remaining = [item for item in indexed if Path(str(item)).resolve() != root]
            atomic_json(_index, sorted(set(remaining)))
    return {"success": True, "workspace": str(root), "deleted": True}


class TextWrite(BaseModel):
    workflow_id: str
    workspace: str
    path: str
    content: str = Field(max_length=10_000_000)


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
