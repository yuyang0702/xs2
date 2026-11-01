#!/usr/bin/env python3
"""Install/update the desktop's local plugin working tree, without network pulls."""
from __future__ import annotations

import os
import json
from pathlib import Path
import sys

from src.environment import get_determinflow_env
from src.startup_plugins import LocalSnapshotPluginStore, sync_local_plugin


class PluginManager:
    REQUIRED_PLUGINS = {"xs2-novel-flywheel": {"name": "XS2 Novel Flywheel"}}

    def __init__(self, root=None, *, source_dir=None, plugins_dir=None):
        self.determinflow_root = Path(root or Path(__file__).parent).resolve()
        data_dir = Path(get_determinflow_env("DATA_DIR", str(self.determinflow_root / "data")))
        self.plugins_dir = Path(plugins_dir or data_dir / "plugins").resolve()
        self.source_dir = Path(source_dir or os.getenv(
            "DETERMINFLOW_LOCAL_PLUGINS_DIR",
            str(self.determinflow_root.parent / "DeterminFlow-Plugins" / "plugins"),
        )).resolve()

    def check_and_install_required_plugins(self):
        from src.extension_host.plugin_preflight import validate_plugin_checkout

        newly_installed = []
        for plugin_id in self.REQUIRED_PLUGINS:
            source = self.source_dir / plugin_id
            store = LocalSnapshotPluginStore(self.plugins_dir, source)
            current = store.get(plugin_id)
            prefix = current.resource_prefix if current is not None else None
            record = sync_local_plugin(
                store, plugin_id, source,
                preflight=lambda checkout: validate_plugin_checkout(
                    plugin_id, checkout, resource_prefix=prefix),
            )
            state = "pending removal preserved" if record.pending_remove else record.active_revision.content_sha256[:12]
            print(f"Local plugin {plugin_id}: {state}", flush=True)
            if current is None:
                newly_installed.append(plugin_id)
        # Bootstrap only a genuinely new configuration. An existing disabled
        # list (or an environment override) is an explicit user choice.
        if newly_installed and get_determinflow_env("EXTENSIONS") is None:
            config_dir = Path(get_determinflow_env("CONFIG_DIR", str(self.determinflow_root / "config")))
            config_dir.mkdir(parents=True, exist_ok=True)
            try:
                with (config_dir / "extensions.json").open("x", encoding="utf-8") as handle:
                    json.dump({"enabled": newly_installed, "strict_startup": False}, handle, indent=2)
            except FileExistsError:
                pass
        return True


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    try:
        return 0 if PluginManager().check_and_install_required_plugins() else 1
    except Exception as exc:
        print(f"Plugin preparation failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
