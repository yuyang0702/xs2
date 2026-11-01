"""Windows launch coordinator, using the selected interpreter and local source."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
import re
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


def load_startup_environment():
    """Read configuration before any install/build/write or service mutation."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        # A new venv needs a stdlib bootstrap. Only startup identity/port keys
        # are required before installing dependencies; secrets are not parsed.
        from src.startup_instances import StartupNotice
        env_file = ROOT / '.env'
        if not env_file.is_file():
            return
        keys = {'WEB_HOST', 'WEB_PORT', 'DETERMINFLOW_DATA_DIR', 'DETERMINFLOW_CONFIG_DIR',
                'AI_COMPANY_DATA_DIR', 'AI_COMPANY_CONFIG_DIR'}
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$', line)
            if not match or match[1] not in keys or match[1] in os.environ:
                continue
            value = match[2]
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise StartupNotice('启动环境中的路径或端口引号不完整，请检查 .env 后重试。')
                value = value[1:-1]
                if '\\' in value and match[2].startswith('"'):
                    raise StartupNotice('首次环境准备无法可靠解析带转义的配置路径，请先安装 requirements.txt 中的依赖后重试。')
            else:
                value = value.split(' #', 1)[0].strip()
            if '${' in value:
                def substitute(found):
                    if found[1] not in os.environ:
                        raise StartupNotice('首次环境准备无法解析配置变量，请先安装 requirements.txt 中的依赖后重试。')
                    return os.environ[found[1]]
                value = re.sub(r'\$\{([^}]+)\}', substitute, value)
            os.environ[match[1]] = value
    else:
        load_dotenv(ROOT / '.env')


def run_startup(*, prepare_only, no_browser, log):
    from src.startup import ensure_python_dependencies, ensure_frontend
    from src.startup_identity import StartupProfile
    from src.startup_instances import StartupLock, StartupNotice, prepare_service_slot
    load_startup_environment()
    profile = StartupProfile.from_root(ROOT)
    host, port = os.getenv('WEB_HOST', '0.0.0.0'), int(os.getenv('WEB_PORT', '8020'))
    with StartupLock(profile) as lock:
        prepare_service_slot(profile, host, port, prepare_only=prepare_only)
        ensure_python_dependencies(ROOT, runner=run_logged)
        if not (ROOT / '.env').exists() and (ROOT / '.env.example').is_file():
            shutil.copy2(ROOT / '.env.example', ROOT / '.env')
        load_startup_environment()
        if StartupProfile.from_root(ROOT) != profile:
            raise StartupNotice('初始配置已生成，启动配置位置发生变化，请再次双击以使用新配置。')
        configured = os.getenv('WEB_HOST', '0.0.0.0'), int(os.getenv('WEB_PORT', '8020'))
        if configured != (host, port):
            host, port = configured
            prepare_service_slot(profile, host, port, prepare_only=prepare_only)
        example = ROOT / 'config' / 'models_config.example.json'
        model_config = profile.config_dir / 'models_config.json'
        if not model_config.exists() and example.is_file():
            profile.config_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(example, model_config)
        ensure_frontend(ROOT, runner=run_logged)
        from setup_plugins import PluginManager
        PluginManager().check_and_install_required_plugins()
        if prepare_only:
            print('Local preparation complete.', flush=True)
            return 0
        from src.startup_runtime import launch_server
        options = {'open_browser': lambda url: None} if no_browser else {}
        return launch_server(ROOT, host, port, log=log, profile=profile, on_ready=lock.release, **options)


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
            from src.startup_instances import StartupNotice
            return run_startup(prepare_only=args.prepare_only, no_browser=args.no_browser, log=None)
        except KeyboardInterrupt:
            print("Service stopped.", flush=True)
            return 130
        except StartupNotice as notice:
            print(str(notice), flush=True)
            return 2
        except Exception:
            traceback.print_exc()
            return 1
        finally:
            sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    raise SystemExit(main())
