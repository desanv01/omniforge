"""Application authority seam for read-only tools; no model-supplied identity."""
import hashlib
import re
from uuid import UUID

from sqlalchemy import text

from services.api.errors import Problem


def bind_read_range(engine, artifact_root, principal_id: UUID, case_id: UUID):
    """Bind only from authenticated application context, never evidence/model text."""
    def read_range(association_id: UUID, expected_sha256: str, start_byte: int, end_byte: int) -> bytes:
        with engine.connect() as conn:
            item = conn.execute(text("""SELECT b.sha256,b.bytes,a.publication_status
                FROM artifact_associations a JOIN artifacts b ON b.id=a.artifact_id
                JOIN case_grants g ON g.case_id=a.case_id
                WHERE a.id=:id AND a.case_id=:case AND g.principal_id=:principal"""),
                {"id": association_id, "case": case_id, "principal": principal_id}).mappings().one_or_none()
        if item is None:
            raise Problem(404, "evidence_not_found", "not_found", "Evidence is unavailable to this case")
        if expected_sha256 != item["sha256"] or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise Problem(409, "evidence_hash_conflict", "conflict", "Evidence hash does not match")
        if (type(start_byte) is not int or type(end_byte) is not int
                or not 0 <= start_byte < end_byte <= item["bytes"] or end_byte-start_byte > 1024*1024):
            raise Problem(422, "invalid_range", "validation", "Invalid half-open byte range")
        if item["publication_status"] != "committed":
            raise Problem(503, "publication_pending", "storage", "Artifact publication is pending", True)
        path = artifact_root / "blobs" / expected_sha256
        if path.is_symlink() or not path.is_file():
            raise Problem(503, "artifact_unavailable", "storage", "Artifact bytes unavailable", True)
        total, value, selection = 0, hashlib.sha256(), bytearray()
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(65536):
                    next_total = total + len(chunk)
                    if next_total > item["bytes"]:
                        raise Problem(503, "artifact_unavailable", "storage", "Artifact bytes failed verification", True)
                    value.update(chunk)
                    left, right = max(start_byte, total), min(end_byte, next_total)
                    if left < right:
                        selection.extend(chunk[left-total:right-total])
                    total = next_total
        except OSError:
            raise Problem(503, "artifact_unavailable", "storage", "Artifact bytes unavailable", True) from None
        if total != item["bytes"] or value.hexdigest() != expected_sha256 or len(selection) != end_byte-start_byte:
            raise Problem(503, "artifact_unavailable", "storage", "Artifact bytes failed verification", True)
        return bytes(selection)
    return read_range
