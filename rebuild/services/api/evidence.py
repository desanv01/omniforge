"""Stream one multipart file to private staging, then journal and publish."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from sqlalchemy import text

from services.api.db import lock
from services.api.errors import Problem
from services.api.contracts import ArtifactAssociation


class Upload:
    def __init__(self, root, content_type, limit):
        media, options = parse_options_header(content_type)
        boundary = options.get(b"boundary", b"")
        if media != b"multipart/form-data" or not 1 <= len(boundary) <= 200:
            raise Problem(415, "multipart_required", "validation", "Use multipart/form-data with one file field")
        self.name = str(uuid4()) + ".stage"
        self.path = root / "staging" / self.name
        self.handle = self.path.open("xb")
        self.limit, self.size, self.wire, self.header_size = limit, 0, 0, 0
        self.hash = hashlib.sha256()
        self.headers, self.field, self.value = {}, b"", b""
        self.parts, self.finished = 0, False
        self.original_name, self.media_type = "", "application/octet-stream"
        self.parser = MultipartParser(boundary, {
            "on_part_begin": self.begin, "on_header_field": self.header_field,
            "on_header_value": self.header_value, "on_header_end": self.header_end,
            "on_headers_finished": self.headers_finished, "on_part_data": self.data,
            "on_end": self.end,
        })

    def begin(self):
        self.parts += 1
        if self.parts != 1:
            raise Problem(422, "one_file_required", "validation", "Exactly one file field is required")

    def header_field(self, data, start, end):
        self.header_size += end-start
        self.check_headers()
        self.field += data[start:end]

    def header_value(self, data, start, end):
        self.header_size += end-start
        self.check_headers()
        self.value += data[start:end]

    def check_headers(self):
        if self.header_size > 8192:
            raise Problem(413, "headers_too_large", "validation", "Multipart headers exceed limit")

    def header_end(self):
        key = self.field.lower()
        if key in self.headers:
            raise Problem(422, "duplicate_header", "validation", "Duplicate multipart header")
        self.headers[key] = self.value
        self.field, self.value = b"", b""

    def headers_finished(self):
        kind, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        if kind != b"form-data" or options.get(b"name") != b"file" or b"filename" not in options:
            raise Problem(422, "file_required", "validation", "Expected file field")
        name = options[b"filename"].decode("utf-8", errors="replace").replace("\\", "/").split("/")[-1]
        self.original_name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127)[:255] or "unnamed"
        mime = self.headers.get(b"content-type", b"application/octet-stream").decode("ascii", errors="replace")
        self.media_type = mime if len(mime) <= 128 and all(32 <= ord(c) < 127 for c in mime) else "application/octet-stream"

    def data(self, data, start, end):
        self.size += end-start
        if self.size > self.limit:
            raise Problem(413, "upload_too_large", "validation", "Artifact exceeds upload limit")
        self.handle.write(data[start:end])
        self.hash.update(data[start:end])

    def end(self):
        self.finished = True

    async def receive(self, request):
        try:
            async for chunk in request.stream():
                self.wire += len(chunk)
                if self.wire > self.limit + 65536:
                    raise Problem(413, "upload_too_large", "validation", "Request exceeds upload limit")
                self.parser.write(chunk)
            self.parser.finalize()
            if not self.finished or self.parts != 1:
                raise Problem(422, "truncated_upload", "validation", "Multipart upload is incomplete")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except Problem:
            raise
        except (ValueError, UnicodeError):
            raise Problem(422, "invalid_multipart", "validation", "Malformed multipart upload") from None
        finally:
            self.handle.close()


ASSOCIATION_SQL = """SELECT a.id,a.case_id,a.artifact_id,a.source_id,a.original_name,a.media_type,
    a.captured_at,a.imported_at,a.publication_status,a.revision,b.sha256,b.bytes
    FROM artifact_associations a JOIN artifacts b ON b.id=a.artifact_id"""


def association(conn, association_id):
    return dict(conn.execute(text(ASSOCIATION_SQL + " WHERE a.id=:id"), {"id": association_id}).mappings().one())


def verify_file(path, expected_hash, expected_bytes):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != expected_bytes:
        return False
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            value.update(chunk)
    return value.hexdigest() == expected_hash


def publish(conn, root, association_id):
    """Called with transaction lock; copies preserve staged original for recovery."""
    item = association(conn, association_id)
    stage_name = conn.execute(text("SELECT stage_name FROM artifact_associations WHERE id=:id"),
                              {"id": association_id}).scalar_one()
    # Database-controlled names are validated before joining paths.
    if Path(stage_name).name != stage_name or "/" in stage_name or "\\" in stage_name:
        raise Problem(503, "publication_unavailable", "storage", "Publication needs reconciliation", True)
    stage = root / "staging" / stage_name
    target = root / "blobs" / item["sha256"]
    lock(conn, "blob:" + item["sha256"])
    if target.exists():
        valid = verify_file(target, item["sha256"], item["bytes"])
    elif verify_file(stage, item["sha256"], item["bytes"]):
        temporary = root / "staging" / (str(uuid4()) + ".publish")
        with stage.open("rb") as source, temporary.open("xb") as output:
            shutil.copyfileobj(source, output, 65536)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        valid = verify_file(target, item["sha256"], item["bytes"])
    else:
        valid = False
    if not valid:
        raise Problem(503, "publication_unavailable", "storage", "Publication needs reconciliation", True)
    conn.execute(text("UPDATE artifact_associations SET publication_status='committed', revision=revision+1 WHERE id=:id AND publication_status='pending'"), {"id": association_id})
    result = association(conn, association_id)
    body = ArtifactAssociation.model_validate(result).model_dump(mode="json")
    conn.execute(text("UPDATE idempotency SET response=CAST(:body AS jsonb),status=201 WHERE response->>'id'=:id AND operation LIKE 'upload:%'"),
                 {"body": json.dumps(body), "id": str(association_id)})
    return result


def reconcile(engine, root, limit=20):
    """Bounded explicit recovery only; no deleting originals/stages/orphan blobs."""
    if not 1 <= limit <= 100:
        raise ValueError("Invalid reconciliation bound")
    repaired, pending = [], []
    with engine.begin() as conn:
        ids = conn.execute(text("SELECT id FROM artifact_associations WHERE publication_status='pending' ORDER BY imported_at,id LIMIT :limit FOR UPDATE SKIP LOCKED"), {"limit": limit}).scalars().all()
        for item_id in ids:
            try:
                with conn.begin_nested():
                    publish(conn, root, item_id)
                repaired.append(str(item_id))
            except (Problem, OSError):
                pending.append(str(item_id))
    return {"repaired": repaired, "pending": pending}
