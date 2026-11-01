"""Child-process lifecycle and launch-specific HTTP readiness."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import ProxyHandler, build_opener
import webbrowser

from src.startup import ensure_port_available
from src.startup_identity import StartupProfile
from src.startup_instances import write_record, cleanup_record, StartupNotice


def add_readiness_route(app, token: str) -> None:
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def ready(request):
        return JSONResponse({"token": token, "pid": os.getpid()},
                            headers={"Cache-Control": "no-store"})

    # The frontend StaticFiles mount is a catch-all and must stay last.
    app.router.routes.insert(0, Route("/api/startup-ready", ready, methods=["GET"]))


def _stop_child(process) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=8)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def launch_server(root: Path, host: str, port: int, *, log=None,
                  open_browser=webbrowser.open, timeout=None, profile=None, on_ready=None) -> int:
    """Launch only our child, verify its nonce, and retain its exit code."""
    if timeout is None:
        from src.config import WORKFLOW_EXECUTOR_COUNT, WORKFLOW_EXECUTOR_MODE
        from src.workflow.executor_timing import server_readiness_timeout
        timeout = server_readiness_timeout(WORKFLOW_EXECUTOR_COUNT if WORKFLOW_EXECUTOR_MODE == 'process' else 1)
    try:
        ensure_port_available(host, port)
    except RuntimeError as error:
        raise StartupNotice(f'准备完成后端口 {port} 已被其他服务占用，本次没有停止其他进程。请稍后再次双击或检查端口设置。') from error
    token = uuid.uuid4().hex
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    profile = profile or StartupProfile.from_root(root)
    env = os.environ.copy()
    env.update(DETERMINFLOW_STARTUP_TOKEN=token, WEB_HOST=host, WEB_PORT=str(port),
               DETERMINFLOW_STARTUP_SECRET=secret,
               DETERMINFLOW_STARTUP_PROFILE_ID=profile.profile_id,
               DETERMINFLOW_LAUNCH_GUARD_FILE=str(profile.guard_file(token)),
               PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        [sys.executable, str(Path(root) / "run.py"), "--serve"], cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    def forward_output():
        for line in process.stdout:
            if log is not None:
                log.write(line)
                log.flush()
            print(line, end="", flush=True)

    reader = threading.Thread(target=forward_output, daemon=True)
    reader.start()
    address = "127.0.0.1" if host in {"0.0.0.0", ""} else "::1" if host == "::" else host
    address = f"[{address}]" if ":" in address else address
    url = f"http://{address}:{port}/"
    # Local readiness must not use system HTTP proxies.
    opener = build_opener(ProxyHandler({}))
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"Server exited before readiness (exit code {code})")
            try:
                with opener.open(url + "api/startup-ready", timeout=1) as response:
                    identity = json.load(response)
                # Windows venv python.exe may be a redirector whose PID differs
                # from the serving interpreter. The random per-launch token is
                # inherited only by this child; a previous server cannot match it.
                if (isinstance(identity, dict) and identity.get("token") == token
                        and isinstance(identity.get("pid"), int) and identity["pid"] > 0):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Server readiness timed out; see the startup log")
        if process.poll() is not None:
            raise RuntimeError("Server exited immediately after readiness")
        write_record(profile, {'protocol': 1, 'project_root': str(profile.root),
                              'profile_id': profile.profile_id, 'host': host, 'port': port,
                              'token': token, 'secret': secret, 'pid': identity['pid']})
        if on_ready is not None:
            on_ready()
        print(f"DeterminFlow ready: {url}\nPress Ctrl+C to stop.", flush=True)
        try:
            open_browser(url + "?_launch=" + token)
        except Exception as exc:
            print(f"Open {url} manually ({exc})", flush=True)
        return process.wait()
    finally:
        _stop_child(process)
        reader.join(timeout=5)
        process.stdout.close()
        cleanup_record(profile, token)
