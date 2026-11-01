"""Windows launch coordinator, using the selected interpreter and local source."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_logged(argv, *, cwd, check=True, timeout=None):
    """Keep native pip/npm output visible and in the startup transcript."""
    completed = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if check:
        completed.check_returncode()
    return completed


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, value):
        self.log.write(value)
        self.console.write(value)
        return len(value)

    def flush(self):
        self.log.flush()
        self.console.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"startup_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}.log"
    print(f"Startup log: {log_path}", flush=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(stdout, log), Tee(stderr, log)
        try:
            from src.startup import ensure_python_dependencies, ensure_frontend, ensure_port_available
            ensure_python_dependencies(ROOT, runner=run_logged)
            if not (ROOT / ".env").exists() and (ROOT / ".env.example").is_file():
                shutil.copy2(ROOT / ".env.example", ROOT / ".env")
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
            from src.environment import get_determinflow_env
            config_dir = Path(get_determinflow_env("CONFIG_DIR", str(ROOT / "config")))
            model_config = config_dir / "models_config.json"
            example = ROOT / "config" / "models_config.example.json"
            if not model_config.exists() and example.is_file():
                config_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(example, model_config)
            host, port = os.getenv("WEB_HOST", "0.0.0.0"), int(os.getenv("WEB_PORT", "8020"))
            ensure_port_available(host, port)
            ensure_frontend(ROOT, runner=run_logged)
            from setup_plugins import PluginManager
            PluginManager().check_and_install_required_plugins()
            if args.prepare_only:
                print("Local preparation complete.", flush=True)
                return 0
            from src.startup_runtime import launch_server
            options = {"open_browser": lambda url: None} if args.no_browser else {}
            return launch_server(ROOT, host, port, **options)
        except KeyboardInterrupt:
            print("Service stopped.", flush=True)
            return 130
        except Exception:
            traceback.print_exc()
            return 1
        finally:
            sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    raise SystemExit(main())
