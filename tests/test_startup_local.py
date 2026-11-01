from pathlib import Path
import json
import socket
import subprocess
import os
import shutil
import sys

import pytest

from src import startup
from src.startup_plugins import LocalSnapshotPluginStore, sync_local_plugin


def frontend(root):
    web = root / "web"
    (web / "src").mkdir(parents=True)
    (web / "public").mkdir()
    (web / "src" / "main.ts").write_text("version one")
    (web / "package.json").write_text('{}')
    (web / "package-lock.json").write_text('{}')
    return web


def builder(web, calls):
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == "build":
            (web / "dist").mkdir(exist_ok=True)
            (web / "dist" / "index.html").write_text("fresh build")
        else:
            (web / "node_modules").mkdir(exist_ok=True)
        return subprocess.CompletedProcess(argv, 0)
    return run


def test_frontend_rebuilds_changed_sources_public_config_and_outputs(tmp_path):
    web = frontend(tmp_path)
    calls = []
    run = builder(web, calls)
    startup.ensure_frontend(tmp_path, runner=run)
    startup.ensure_frontend(tmp_path, runner=run)
    assert [a[-1] for a in calls] == ["ci", "build"]
    for relative in ("src/main.ts", "public/icon.svg", "vite.config.ts", "package-lock.json", "dist/index.html"):
        (web / relative).write_text("changed")
        before = len(calls)
        startup.ensure_frontend(tmp_path, runner=run)
        assert len(calls) > before, relative
        assert (web / "dist" / "index.html").read_text() == "fresh build"


def test_frontend_failed_build_does_not_accept_old_dist(tmp_path):
    web = frontend(tmp_path)
    startup.ensure_frontend(tmp_path, runner=builder(web, []))
    (web / "src" / "main.ts").write_text("broken change")
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(7, argv)
    with pytest.raises(subprocess.CalledProcessError):
        startup.ensure_frontend(tmp_path, runner=fail)
    calls = []
    startup.ensure_frontend(tmp_path, runner=builder(web, calls))
    assert calls[-1][-1] == "build"


def test_frontend_rebuilds_added_changed_and_removed_extension_modules(tmp_path):
    web = frontend(tmp_path)
    calls = []
    run = builder(web, calls)
    startup.ensure_frontend(tmp_path, runner=run)
    extension = tmp_path / "extensions" / "demo" / "frontend"
    extension.mkdir(parents=True)
    entrypoint = extension / "index.tsx"
    entrypoint.write_text("export default 'new extension'")
    startup.ensure_frontend(tmp_path, runner=run)
    assert [argv[-1] for argv in calls] == ["ci", "build", "build"]
    entrypoint.write_text("export default 'changed extension'")
    startup.ensure_frontend(tmp_path, runner=run)
    assert len(calls) == 4
    component = extension / "nested" / "Component.tsx"
    component.parent.mkdir()
    component.write_text("export const Component = () => null")
    startup.ensure_frontend(tmp_path, runner=run)
    assert len(calls) == 5
    component.unlink()
    entrypoint.unlink()
    startup.ensure_frontend(tmp_path, runner=run)
    assert len(calls) == 6
    startup.ensure_frontend(tmp_path, runner=run)
    assert len(calls) == 6


def test_dependencies_only_mark_success_and_reinstall_after_requirements_change(tmp_path):
    (tmp_path / "requirements.txt").write_text("first==1\n")
    calls = []
    def install(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    startup.ensure_python_dependencies(tmp_path, runner=install)
    startup.ensure_python_dependencies(tmp_path, runner=install)
    assert len(calls) == 1
    (tmp_path / "requirements.txt").write_text("second==2\n")
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(5, argv)
    with pytest.raises(subprocess.CalledProcessError):
        startup.ensure_python_dependencies(tmp_path, runner=fail)
    startup.ensure_python_dependencies(tmp_path, runner=install)
    assert len(calls) == 2


def test_occupied_custom_port_fails_without_contacting_old_service():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with pytest.raises(RuntimeError, match="occupied|in use"):
            startup.ensure_port_available("127.0.0.1", occupied.getsockname()[1])


def package(root):
    root.mkdir()
    (root / "extension.toml").write_text('[extension]\nid="demo"\nname="Demo"\nversion="1.0"\napi_version="1"\n[resource_namespace]\nprefix="demo"\n')
    (root / "payload.txt").write_text("original")
    return root


def test_snapshot_installs_real_checkout_and_updates_uncommitted_files_idempotently(tmp_path):
    source = package(tmp_path / "local source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    first = sync_local_plugin(store, "demo", source)
    old = Path(first.active_revision.checkout_path)
    assert old != source
    assert (old / "payload.txt").read_text() == "original"
    store.apply_pending()
    lock = store.lock_path.read_bytes()
    sync_local_plugin(store, "demo", source)
    assert store.lock_path.read_bytes() == lock
    (source / "payload.txt").write_text("uncommitted latest")
    new = sync_local_plugin(store, "demo", source)
    assert Path(new.active_revision.checkout_path) != old
    assert (Path(new.active_revision.checkout_path) / "payload.txt").read_text() == "uncommitted latest"
    assert (old / "payload.txt").read_text() == "original"
    assert first.active_revision in new.history


def test_snapshot_preserves_resource_prefix_source_and_external_configuration(tmp_path):
    source = package(tmp_path / "source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    first = store.install("demo", source.as_uri(), resource_prefix="renamed", acknowledge_risk=True)
    config = tmp_path / "extensions.json"
    config.write_text('{"enabled": [], "demo": {"model":"keep-me"}}')
    original = config.read_bytes()
    (source / "payload.txt").write_text("changed")
    current = sync_local_plugin(store, "demo", source)
    assert current.resource_prefix == "renamed"
    assert current.resource_prefix_override == "renamed"
    assert current.source == first.source
    assert config.read_bytes() == original


def test_snapshot_does_not_cancel_pending_uninstall(tmp_path):
    source = package(tmp_path / "source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    sync_local_plugin(store, "demo", source)
    store.mark_uninstall("demo")
    (source / "payload.txt").write_text("changed")
    assert sync_local_plugin(store, "demo", source).pending_remove


def test_invalid_snapshot_leaves_active_revision_unchanged(tmp_path):
    source = package(tmp_path / "source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    first = sync_local_plugin(store, "demo", source)
    (source / "extension.toml").write_text("invalid toml[")
    with pytest.raises(Exception):
        sync_local_plugin(store, "demo", source)
    assert store.get("demo") == first


def test_snapshot_checkout_fits_windows_deployment_path_budget(tmp_path):
    source = package(tmp_path / "source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    record = sync_local_plugin(store, "demo", source)
    revision_directory = Path(record.active_revision.checkout_path).name
    # Longest vendor resource that failed deployment under ordinary Windows
    # paths; revision naming must leave enough room for this packaged file.
    deployed = Path("C:/xs2/DeterminFlow/data/plugins/checkouts/xs2-novel-flywheel") / revision_directory
    vendor_file = deployed / "resources/script-library/xs2/reference_distill/vendor/writing-dna-skill/templates/author-corpus/zh/_meta/example.schema.json"
    assert len(str(vendor_file)) < 260
    assert len(store.verify("demo").active_revision.content_sha256) == 64


def test_windows_plugin_source_paths_with_spaces_are_local(tmp_path):
    from src.plugin_system.source_selection import canonicalize_plugin_source
    source = tmp_path / "local plugin source"
    assert canonicalize_plugin_source(str(source)) == (source.as_uri(), "local", source.as_uri())


def test_readiness_route_precedes_frontend_catchall():
    import os
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.responses import PlainTextResponse
    from src.startup_runtime import add_readiness_route
    app = FastAPI()
    @app.get("/{path:path}")
    def frontend(path):
        return PlainTextResponse("stale frontend")
    add_readiness_route(app, "unique-launch")
    with TestClient(app) as client:
        response = client.get("/api/startup-ready")
        assert response.json() == {"token": "unique-launch", "pid": os.getpid()}


def test_launcher_verifies_child_identity_logs_output_and_uses_custom_port(tmp_path):
    from src.startup_runtime import launch_server
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    (tmp_path / "run.py").write_text('''
import os, json, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"token":os.environ["DETERMINFLOW_STARTUP_TOKEN"],"pid":os.getpid()}).encode())
        threading.Timer(0.3, server.shutdown).start()
server = HTTPServer(("127.0.0.1", int(os.environ["WEB_PORT"])), Handler)
print("child output reached log", flush=True)
server.serve_forever(poll_interval=0.05)
''')
    urls = []
    log = tmp_path / "startup.log"
    with log.open("w", encoding="utf-8") as handle:
        result = launch_server(tmp_path, "127.0.0.1", port, log=handle, open_browser=urls.append, timeout=10)
    assert result == 0
    assert "child output reached log" in log.read_text()
    assert urls and f":{port}/" in urls[0]


def test_launcher_rejects_wrong_identity_and_stops_its_child(tmp_path):
    from src.startup_runtime import launch_server
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    (tmp_path / "run.py").write_text('''
import os, json
from http.server import HTTPServer, BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"token":"old-process","pid":os.getpid()}).encode())
HTTPServer(("127.0.0.1", int(os.environ["WEB_PORT"])), Handler).serve_forever()
''')
    urls = []
    with pytest.raises(RuntimeError, match="readiness|ready"):
        launch_server(tmp_path, "127.0.0.1", port, open_browser=urls.append, timeout=0.8)
    assert urls == []
    startup.ensure_port_available("127.0.0.1", port)


@pytest.mark.skipif(os.name != "nt", reason="Windows bootstrap")
def test_powershell_and_batch_handle_spaces_and_propagate_failure(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "start_local.py").write_text('import sys\nprint("selected-interpreter=" + sys.executable)\nraise SystemExit(7)\n')
    repository = Path(__file__).resolve().parents[1]
    for filename in ("start_determinflow_v2.ps1", "start_determinflow.bat"):
        shutil.copy2(repository / filename, root / filename)
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True)
    env = dict(os.environ, DETERMINFLOW_NO_PAUSE="1")
    for command in (["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "start_determinflow_v2.ps1")],
                    ["cmd.exe", "/d", "/c", "start_determinflow.bat"]):
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 7, result.stdout + result.stderr
        assert "selected-interpreter=" + str(root / ".venv" / "Scripts" / "python.exe") in result.stdout


def test_snapshot_keeps_implicit_existing_prefix_when_manifest_changes(tmp_path):
    source = package(tmp_path / "source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    sync_local_plugin(store, "demo", source)
    manifest = source / "extension.toml"
    manifest.write_text(manifest.read_text().replace('prefix="demo"', 'prefix="changed"'))
    current = sync_local_plugin(store, "demo", source)
    assert current.resource_prefix == "demo"
    assert current.resource_prefix_override is None


def test_snapshot_failed_preflight_does_not_replace_lock(tmp_path):
    source = package(tmp_path / "source")
    store = LocalSnapshotPluginStore(tmp_path / "store", source)
    first = sync_local_plugin(store, "demo", source)
    (source / "payload.txt").write_text("bad resource")
    def fail(checkout):
        raise ValueError("invalid plugin resource")
    with pytest.raises(ValueError, match="invalid plugin resource"):
        sync_local_plugin(store, "demo", source, preflight=fail)
    assert store.get("demo") == first


@pytest.mark.parametrize("existing", [None, '{"enabled": [], "strict_startup": true}'])
def test_plugin_setup_initializes_first_install_but_preserves_existing_disabled_config(tmp_path, monkeypatch, existing):
    from setup_plugins import PluginManager
    sources = tmp_path / "sources"
    sources.mkdir()
    package(sources / "demo")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    configuration = config_dir / "extensions.json"
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("DETERMINFLOW_EXTENSIONS", raising=False)
    monkeypatch.delenv("AI_COMPANY_EXTENSIONS", raising=False)
    if existing is not None:
        configuration.write_text(existing)
    manager = PluginManager(tmp_path, source_dir=sources, plugins_dir=tmp_path / "store")
    manager.REQUIRED_PLUGINS = {"demo": {}}
    assert manager.check_and_install_required_plugins()
    if existing is None:
        assert json.loads(configuration.read_text())["enabled"] == ["demo"]
    else:
        assert configuration.read_text() == existing
