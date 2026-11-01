"""Stage local working files through PluginStore's immutable revision machinery.

No Git checkout, commit, fetch, config rewrite or enabled-state change occurs.
The adapter overrides only package materialization; normal Store validation,
lock serialization, rollback history and checkout verification remain in use.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from src.plugin_system import PluginStore
from src.plugin_system.integrity import plugin_content_sha256


@contextmanager
def _snapshot(source: Path, staging: Path):
    with tempfile.TemporaryDirectory(prefix="local-source-", dir=staging) as temporary:
        prepared = Path(temporary) / "package"
        shutil.copytree(source, prepared, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo", ".pytest_cache"))
        yield prepared


class LocalSnapshotPluginStore(PluginStore):
    def __init__(self, root: Path, snapshot_source: Path):
        super().__init__(root)
        self.snapshot_source = Path(snapshot_source).resolve()
        self._preserved_prefix = None

    def _manifest_resource_prefix(self, revision):
        declared = super()._manifest_resource_prefix(revision)
        return declared if self._preserved_prefix is None else self._preserved_prefix

    def _materialize(self, plugin_id, canonical_source, clone_source, ref,
                     subdirectory, *, preflight=None):
        with _snapshot(self.snapshot_source, self.staging_dir) as prepared:
            self._validate_package_root(plugin_id, prepared, prepared)
            digest = plugin_content_sha256(prepared)
            # Use a Git-sized synthetic revision to keep ordinary Windows paths
            # below MAX_PATH. The full SHA-256 remains the content identity and
            # is checked by PluginStore, including on every subsequent launch.
            return self._place_checkout(plugin_id, digest[:40], prepared, "local-working-tree",
                                        expected_content_sha256=digest, preflight=preflight)


def sync_local_plugin(store: LocalSnapshotPluginStore, plugin_id: str, source: Path,
                      *, preflight=None):
    current = store.get(plugin_id)
    if current is not None and current.pending_remove:
        return current
    source = Path(source).resolve()
    if not source.is_dir():
        if current is not None:
            return store.verify(plugin_id)
        raise RuntimeError(f"Local plugin source is missing: {source}")
    with _snapshot(source, store.staging_dir) as prepared:
        store._validate_package_root(plugin_id, prepared, prepared)
        digest = plugin_content_sha256(prepared)
        if current is not None and current.active_revision.content_sha256 == digest:
            return store.verify(plugin_id)
        previous_source = store.snapshot_source
        store.snapshot_source = prepared
        store._preserved_prefix = current.resource_prefix if current is not None else None
        try:
            if current is None:
                return store.install(plugin_id, source.as_uri(), acknowledge_risk=True, preflight=preflight)
            # Preserve the existing source, subdirectory, explicit prefix and history.
            return store.update(plugin_id, acknowledge_risk=True, preflight=preflight)
        finally:
            store.snapshot_source = previous_source
            store._preserved_prefix = None
