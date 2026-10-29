"""Explicit trusted-development receiver settings; import performs no I/O."""
from dataclasses import dataclass, field
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import make_url

ROLE = "omniforge_b3c_receiver_v1"
DATABASE = "omniforge_rebuild"
MIGRATION = "0009_provider_diagnostics"


class WorkerSettingsError(Exception):
    def __init__(self):
        super().__init__("Invalid explicit worker configuration")


@dataclass(frozen=True)
class WorkerSettings:
    schema_version: int
    database_url: str = field(repr=False)
    allowed_run_ids: tuple[UUID, ...]

    def __post_init__(self):
        try:
            if type(self.schema_version) is not int or self.schema_version != 1:
                raise ValueError()
            if type(self.database_url) is not str or len(self.database_url) > 2048:
                raise ValueError()
            url = make_url(self.database_url)
            if (url.drivername != "postgresql+psycopg" or url.username != ROLE or
                url.host != "of-core-db" or url.port != 5432 or url.database != DATABASE or
                url.query or type(url.password) is not str or not 1 <= len(url.password) <= 256 or
                any(ord(ch) < 32 or ord(ch) == 127 for ch in url.password)):
                raise ValueError()
            if (type(self.allowed_run_ids) is not tuple or len(self.allowed_run_ids) != 7 or
                any(type(value) is not UUID for value in self.allowed_run_ids) or
                len(set(self.allowed_run_ids)) != 7):
                raise ValueError()
        except Exception:
            raise WorkerSettingsError() from None

    def require_run(self, run_id):
        if type(run_id) is not UUID or run_id not in self.allowed_run_ids:
            raise WorkerSettingsError()
        return run_id


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkerSettingsError()
        result[key] = value
    return result


def load_worker_settings(explicit_path, *, read_bytes=None):
    """Future private path only; tests inject a reader and never read credentials."""
    try:
        if type(explicit_path) is not str or len(explicit_path) > 4096 or not explicit_path:
            raise ValueError()
        if (not Path(explicit_path).is_absolute() or "\x00" in explicit_path or "://" in explicit_path
            or explicit_path.startswith(("~", "\\\\", "//"))):
            raise ValueError()
        reader = read_bytes or (lambda path: Path(path).read_bytes())
        raw = reader(explicit_path)
        if type(raw) is not bytes or not 1 <= len(raw) <= 16384:
            raise ValueError()
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if type(body) is not dict or set(body) != {"schema_version", "database_url", "allowed_run_ids"}:
            raise ValueError()
        if type(body["allowed_run_ids"]) is not list:
            raise ValueError()
        ids = []
        for value in body["allowed_run_ids"]:
            if type(value) is not str:
                raise ValueError()
            parsed = UUID(value)
            if str(parsed) != value:
                raise ValueError()
            ids.append(parsed)
        return WorkerSettings(body["schema_version"], body["database_url"], tuple(ids))
    except Exception:
        raise WorkerSettingsError() from None
