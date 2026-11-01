"""Run the current local source. The Windows launcher prepares before serving."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def prepare():
    from src.startup import ensure_frontend
    from setup_plugins import PluginManager

    ensure_frontend(ROOT)
    PluginManager().check_and_install_required_plugins()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Serve assets already prepared by the launcher")
    parser.add_argument("--prepare", action="store_true", help="Prepare local frontend and plugins, then exit")
    args = parser.parse_args()
    os.chdir(ROOT)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from src.startup import ensure_port_available

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8020"))
    if not args.prepare:
        ensure_port_available(host, port)
    if not args.serve:
        prepare()
    if args.prepare:
        return 0

    os.environ.setdefault("LOG_LEVEL", "INFO")
    from src.web_server import app
    from src.startup_runtime import add_readiness_route
    import uvicorn

    token = os.getenv("DETERMINFLOW_STARTUP_TOKEN")
    if token:
        add_readiness_route(app, token)
    print(f"DeterminFlow: http://localhost:{port}", flush=True)
    config = uvicorn.Config(
        app, host=host, port=port, reload=False, log_level="info",
        limit_concurrency=int(os.getenv("UVICORN_LIMIT_CONCURRENCY", "200")),
        backlog=int(os.getenv("UVICORN_BACKLOG", "2048")),
    )
    server = uvicorn.Server(config)
    secret = os.getenv('DETERMINFLOW_STARTUP_SECRET')
    if token and secret:
        from src.startup_control import install_control
        from src.startup_identity import StartupProfile
        profile = StartupProfile.from_root(ROOT)
        if os.getenv('DETERMINFLOW_STARTUP_PROFILE_ID') != profile.profile_id:
            raise RuntimeError('启动配置身份已变化，请重新启动。')
        install_control(app, root=ROOT, profile_id=profile.profile_id, token=token,
                        secret=secret, guard_file=profile.guard_file(token),
                        shutdown=lambda: setattr(server, 'should_exit', True))
    server.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Startup failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
