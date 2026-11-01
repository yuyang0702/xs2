"""Exercise launcher restart handshakes against isolated, owned HTTP children."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
OPENER = build_opener(ProxyHandler({}))


CHILD_SOURCE = r'''
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace

root = Path(__file__).resolve().parent
os.environ["DETERMINFLOW_DATA_DIR"] = str(root / "data")
os.environ["DETERMINFLOW_CONFIG_DIR"] = str(root / "config")
sys.path.insert(0, __REPOSITORY__)
from fastapi import FastAPI
import uvicorn
import src.startup_control as control
from src.startup_runtime import add_readiness_route

control.WORKFLOWS_DIR = root / "workflows"
@asynccontextmanager
async def lifespan(app):
    yield
    delay = root / "shutdown-delay"
    if delay.exists():
        await asyncio.sleep(float(delay.read_text()))
    (root / "shutdown-finished").touch()
app = FastAPI(lifespan=lifespan)
class Session:
    @property
    def invocation_active(self):
        return (root / "busy").exists()
app.state.session_manager = SimpleNamespace(sessions={"main": Session()})
app.state.workflow_manager = SimpleNamespace(_running_tasks={})
app.state.workflow_executor_pool = None
app.state.roundtable_manager = None
app.state.novel_automation = None
version = (root / "source-version.txt").read_text()
@app.get("/version")
async def version_route():
    return {"version": version, "pid": os.getpid()}
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1",
    port=int(os.environ["WEB_PORT"]), log_level="error"))
add_readiness_route(app, os.environ["DETERMINFLOW_STARTUP_TOKEN"])
control.install_control(app, root=root,
    profile_id=os.environ["DETERMINFLOW_STARTUP_PROFILE_ID"],
    token=os.environ["DETERMINFLOW_STARTUP_TOKEN"],
    secret=os.environ["DETERMINFLOW_STARTUP_SECRET"],
    guard_file=Path(os.environ["DETERMINFLOW_LAUNCH_GUARD_FILE"]),
    shutdown=lambda: setattr(server, "should_exit", True))
server.run()
'''


def _port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get(port, path):
    with OPENER.open(f"http://127.0.0.1:{port}/{path}", timeout=3) as response:
        return json.load(response)


class Launcher:
    def __init__(self, root, profile, port):
        self.root, self.profile, self.port = root, profile, port
        self.ready = threading.Event()
        self.errors = []
        self.results = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from src.startup_runtime import launch_server
        try:
            self.results.append(launch_server(
                self.root, "127.0.0.1", self.port, profile=self.profile,
                on_ready=self.ready.set, open_browser=lambda url: None, timeout=15,
            ))
        except BaseException as exc:
            self.errors.append(exc)
            self.ready.set()

    def start(self):
        self.thread.start()
        assert self.ready.wait(20), "isolated server did not become ready"
        assert not self.errors, self.errors
        assert self.thread.is_alive()
        return self

    def joined(self):
        self.thread.join(10)
        assert not self.thread.is_alive(), "isolated server did not stop gracefully"
        assert not self.errors, self.errors
        assert self.results == [0]


@pytest.fixture
def isolated_service(tmp_path, monkeypatch):
    from src.startup_identity import StartupProfile
    from src.startup_instances import prepare_service_slot

    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setenv("DETERMINFLOW_DATA_DIR", str(root / "data"))
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", str(root / "config"))
    (root / "run.py").write_text(
        CHILD_SOURCE.replace("__REPOSITORY__", repr(str(REPOSITORY))), encoding="utf-8",
    )
    (root / "source-version.txt").write_text("version one", encoding="utf-8")
    profile = StartupProfile.from_root(root)
    port = _port()
    launched = []

    def start():
        launcher = Launcher(root, profile, port).start()
        launched.append(launcher)
        return launcher

    yield root, profile, port, start

    (root / "busy").unlink(missing_ok=True)
    if any(launcher.thread.is_alive() for launcher in launched):
        prepare_service_slot(profile, "127.0.0.1", port, timeout=15)
    for launcher in launched:
        launcher.joined()


def test_second_launch_restarts_owned_idle_service_and_loads_new_source(isolated_service):
    from src.startup_instances import prepare_service_slot

    root, profile, port, start = isolated_service
    first = start()
    original = _get(port, "version")
    first_identity = _get(port, "api/startup-ready")
    (root / "source-version.txt").write_text("latest local source", encoding="utf-8")

    prepare_service_slot(profile, "127.0.0.1", port, timeout=15)
    first.joined()
    start()

    current = _get(port, "version")
    current_identity = _get(port, "api/startup-ready")
    assert original["version"] == "version one"
    assert current["version"] == "latest local source"
    assert current["pid"] != original["pid"]
    assert current_identity["token"] != first_identity["token"]


def test_busy_relaunch_preserves_process_and_does_not_prepare(isolated_service):
    from src.startup_instances import StartupNotice, prepare_service_slot

    root, profile, port, start = isolated_service
    start()
    original = _get(port, "version")
    (root / "busy").write_text("active invocation", encoding="utf-8")
    untouched = root / "user-config.json"
    untouched.write_bytes(b'{"keep": "exactly"}\n')
    original_config = untouched.read_bytes()
    prepared = root / "unexpected-preparation"

    with pytest.raises(StartupNotice):
        prepare_service_slot(profile, "127.0.0.1", port, timeout=3)
        prepared.write_text("must not run", encoding="utf-8")

    assert _get(port, "version") == original
    assert untouched.read_bytes() == original_config
    assert not prepared.exists()


def test_restart_waits_for_owned_shutdown_cleanup(isolated_service):
    from src.startup_instances import prepare_service_slot

    root, profile, port, start = isolated_service
    first = start()
    (root / "shutdown-delay").write_text("1.0", encoding="utf-8")
    prepare_service_slot(profile, "127.0.0.1", port, timeout=15)
    assert (root / "shutdown-finished").is_file()
    first.joined()


def test_relaunch_during_shutdown_cannot_prepare_before_owned_process_exits(isolated_service):
    from src.startup_instances import StartupNotice, prepare_service_slot

    root, profile, port, start = isolated_service
    first = start()
    (root / "shutdown-delay").write_text("3.0", encoding="utf-8")
    with pytest.raises(StartupNotice):
        prepare_service_slot(profile, "127.0.0.1", port, timeout=0.01)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                pass
        except OSError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("isolated service did not enter graceful shutdown")
    try:
        prepare_service_slot(profile, "127.0.0.1", port, timeout=0.1)
    except StartupNotice:
        pass
    else:
        assert (root / "shutdown-finished").is_file()
    first.joined()


def test_prepare_only_preserves_running_owned_service(isolated_service):
    from src.startup_instances import StartupNotice, prepare_service_slot

    _, profile, port, start = isolated_service
    start()
    original = _get(port, "version")
    with pytest.raises(StartupNotice):
        prepare_service_slot(profile, "127.0.0.1", port, prepare_only=True, timeout=3)
    assert _get(port, "version") == original


def test_wrong_profile_cannot_stop_service(isolated_service, monkeypatch):
    from src.startup_identity import StartupProfile
    from src.startup_instances import StartupNotice, prepare_service_slot

    root, _, port, start = isolated_service
    start()
    original = _get(port, "version")
    other = root.parent / "other-checkout"
    other.mkdir()
    monkeypatch.setenv("DETERMINFLOW_DATA_DIR", str(other / "data"))
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", str(other / "config"))
    wrong = StartupProfile.from_root(other)
    with pytest.raises(StartupNotice):
        prepare_service_slot(wrong, "127.0.0.1", port, timeout=3)
    assert _get(port, "version") == original


@pytest.mark.parametrize("field", ["secret", "token"])
def test_bad_secret_or_stale_identity_cannot_stop_service(isolated_service, field):
    from src.startup_instances import StartupNotice, prepare_service_slot

    _, profile, port, start = isolated_service
    start()
    original = _get(port, "version")
    record_bytes = profile.record_file.read_bytes()
    record = json.loads(record_bytes)
    record[field] = "wrong-or-stale-value"
    try:
        profile.record_file.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(StartupNotice):
            prepare_service_slot(profile, "127.0.0.1", port, timeout=3)
        assert _get(port, "version") == original
    finally:
        profile.record_file.write_bytes(record_bytes)


@pytest.mark.parametrize("invalid_host", [None, []])
def test_malformed_record_is_a_friendly_pause_and_preserves_service(isolated_service, invalid_host):
    from src.startup_instances import StartupNotice, prepare_service_slot

    _, profile, port, start = isolated_service
    start()
    original = _get(port, "version")
    record_bytes = profile.record_file.read_bytes()
    record = json.loads(record_bytes)
    if invalid_host is None:
        record.pop("host")
    else:
        record["host"] = invalid_host
    try:
        profile.record_file.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(StartupNotice):
            prepare_service_slot(profile, "127.0.0.1", port, timeout=3)
        assert _get(port, "version") == original
    finally:
        profile.record_file.write_bytes(record_bytes)


def test_unrelated_listener_is_not_contacted_or_stopped(tmp_path, monkeypatch):
    from src.startup_identity import StartupProfile
    from src.startup_instances import StartupNotice, prepare_service_slot

    monkeypatch.setenv("DETERMINFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", str(tmp_path / "config"))
    profile = StartupProfile.from_root(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(StartupNotice):
            prepare_service_slot(profile, "127.0.0.1", port, timeout=1)
        assert listener.fileno() >= 0
        # A plain occupied port gives no authority to probe arbitrary services.
        listener.settimeout(0.1)
        with pytest.raises(TimeoutError):
            listener.accept()


def test_startup_lock_excludes_another_launcher_process(tmp_path, monkeypatch):
    from src.startup_identity import StartupProfile
    from src.startup_instances import StartupLock

    monkeypatch.setenv("DETERMINFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", str(tmp_path / "config"))
    profile = StartupProfile.from_root(tmp_path)
    script = """
import sys
from pathlib import Path
from src.startup_identity import StartupProfile
from src.startup_instances import StartupLock, StartupNotice
try:
    with StartupLock(StartupProfile.from_root(Path(sys.argv[1]))):
        raise SystemExit(9)
except StartupNotice:
    print('concurrent launch preserved')
"""
    with StartupLock(profile):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)], cwd=REPOSITORY,
            env=os.environ.copy(), capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "concurrent launch preserved" in result.stdout
    with StartupLock(profile):
        pass
