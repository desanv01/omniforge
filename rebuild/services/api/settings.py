"""Explicit private configuration; no automatic environment/legacy discovery."""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class Settings:
    database_url: str
    artifact_root: Path
    upload_limit: int = 25 * 1024 * 1024

    def __post_init__(self):
        url = make_url(self.database_url)
        if (url.drivername != "postgresql+psycopg" or url.host != "127.0.0.1"
                or not (url.database or "").startswith("omniforge_rebuild")):
            raise ValueError("Requires an isolated loopback rebuild database")
        source = Path(__file__).resolve().parents[2]
        root = self.artifact_root.resolve()
        if root == source or source in root.parents:
            raise ValueError("Artifact root must be outside source")
        if not root.is_absolute() or not 1 <= self.upload_limit <= 25 * 1024 * 1024:
            raise ValueError("Invalid artifact settings")
        object.__setattr__(self, "artifact_root", root)

    @classmethod
    def from_env(cls):
        path = os.environ.get("OMNIFORGE_CONFIG")
        if not path:
            return None
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(database_url=data["database_url"], artifact_root=Path(data["artifact_root"]))
