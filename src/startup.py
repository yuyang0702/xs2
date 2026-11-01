"""Local desktop startup preparation. Importing this module has no side effects."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def _fingerprint(root: Path, paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_marker(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_marker(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def ensure_python_dependencies(root: Path, *, runner=subprocess.run) -> None:
    root = Path(root)
    requirements = root / "requirements.txt"
    if not requirements.is_file():
        raise RuntimeError(f"Missing Python requirements: {requirements}")
    paths = list(root.glob("requirements*.txt"))
    for name in ("pyproject.toml", "uv.lock"):
        if (root / name).is_file():
            paths.append(root / name)
    expected = {"inputs": _fingerprint(root, paths), "python": sys.version,
                "executable": sys.executable}
    marker = root / ".venv" / ".determinflow-dependencies.json"
    if _read_marker(marker) == expected:
        print("Python dependencies unchanged.", flush=True)
        return
    print("Installing changed Python dependencies...", flush=True)
    runner([sys.executable, "-m", "pip", "install", "-r", str(requirements)],
           cwd=str(root), check=True)
    _write_marker(marker, expected)


def _frontend_inputs(web: Path):
    for name in ("src", "public"):
        directory = web / name
        if directory.is_dir():
            yield from (path for path in directory.rglob("*") if path.is_file())
    for path in web.iterdir():
        if path.is_file() and (path.suffix in {".json", ".js", ".ts", ".mjs", ".cjs", ".mts", ".cts", ".html", ".css"}
                               or path.name.startswith(".env")):
            yield path
    # registry.ts discovers these modules at build time with import.meta.glob;
    # their presence, absence and recursively imported files affect the bundle.
    for directory in (web.parent / "extensions").glob("*/frontend"):
        if directory.is_dir():
            yield from (path for path in directory.rglob("*") if path.is_file())


def _frontend_outputs(web: Path):
    return [path for path in (web / "dist").rglob("*")
            if path.is_file() and path.name != ".determinflow-build.json"]


def ensure_frontend(root: Path, *, runner=subprocess.run) -> None:
    web = Path(root) / "web"
    if not (web / "src").is_dir():
        return  # Distributed API-only builds do not contain frontend source.
    source_hash = _fingerprint(web.parent, _frontend_inputs(web))
    marker = web / "dist" / ".determinflow-build.json"
    expected = {"inputs": source_hash, "outputs": _fingerprint(web, _frontend_outputs(web))}
    if (web / "dist" / "index.html").is_file() and _read_marker(marker) == expected:
        print("Frontend matches current local source.", flush=True)
        return
    npm = "npm.cmd" if os.name == "nt" else "npm"
    dependency_hash = _fingerprint(web, [p for p in (web / "package.json", web / "package-lock.json") if p.is_file()])
    dependency_marker = web / "node_modules" / ".determinflow-dependencies.json"
    if _read_marker(dependency_marker) != dependency_hash:
        print("Installing changed frontend dependencies...", flush=True)
        runner([npm, "ci" if (web / "package-lock.json").exists() else "install"],
               cwd=str(web), check=True, timeout=600)
        _write_marker(dependency_marker, dependency_hash)
    print("Building current local frontend...", flush=True)
    runner([npm, "run", "build"], cwd=str(web), check=True, timeout=600)
    if not (web / "dist" / "index.html").is_file():
        raise RuntimeError("Frontend build did not produce dist/index.html")
    if _fingerprint(web.parent, _frontend_inputs(web)) != source_hash:
        raise RuntimeError("Frontend source changed during build; restart to build a consistent version")
    _write_marker(marker, {"inputs": source_hash, "outputs": _fingerprint(web, _frontend_outputs(web))})


def ensure_port_available(host: str, port: int) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("WEB_PORT must be between 1 and 65535")
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise RuntimeError(f"Cannot start: port {port} on {host} is occupied or unavailable. Stop the existing service or change WEB_PORT.") from exc
