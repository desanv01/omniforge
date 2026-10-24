"""Preserve submitted capture provenance; existing original offsets are unknown."""
from alembic import op

revision = "0002_capture"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""ALTER TABLE artifact_associations
        ADD COLUMN captured_at_original text,
        ADD COLUMN captured_at_offset text,
        ADD COLUMN captured_at_provenance text NOT NULL DEFAULT 'unknown',
        ADD CONSTRAINT capture_provenance_state CHECK (
          (captured_at_provenance='unknown' AND captured_at_original IS NULL AND captured_at_offset IS NULL)
          OR (captured_at_provenance='supplied' AND captured_at IS NOT NULL
              AND captured_at_original IS NOT NULL AND captured_at_offset IS NOT NULL))""")


def downgrade():
    raise RuntimeError("Destructive downgrade is not provided; preserve provenance")
