"""Identity for one checkout and its data/configuration profile; no file writes."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from src.environment import get_determinflow_env


@dataclass(frozen=True)
class StartupProfile:
    root: Path
    data_dir: Path
    config_dir: Path
    profile_id: str

    @classmethod
    def from_root(cls, root):
        root = Path(root).resolve()
        def resolved(value):
            path = Path(value).expanduser()
            return (path if path.is_absolute() else root / path).resolve()
        data = resolved(get_determinflow_env('DATA_DIR', str(root / 'data')))
        config = resolved(get_determinflow_env('CONFIG_DIR', str(root / 'config')))
        identity = [os.path.normcase(str(path)) for path in (root, data, config)]
        digest = hashlib.sha256(json.dumps(identity).encode('utf-8')).hexdigest()[:24]
        return cls(root, data, config, digest)

    @property
    def record_file(self):
        return self.root / 'logs' / f'.startup-{self.profile_id}.json'

    @property
    def lock_file(self):
        return self.root / 'logs' / f'.startup-{self.profile_id}.lock'

    def guard_file(self, token):
        return self.root / 'logs' / f'.startup-{self.profile_id}-{token[:20]}.closing'
