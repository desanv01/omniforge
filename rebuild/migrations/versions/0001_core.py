"""Initial isolated core schema. No legacy access or destructive downgrade."""
from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        """CREATE TABLE principals (id uuid PRIMARY KEY, label text NOT NULL,
           token_hash char(64) NOT NULL UNIQUE)""",
        """CREATE TABLE cases (id uuid PRIMARY KEY, revision integer NOT NULL CHECK(revision > 0),
           title text NOT NULL, objective text NOT NULL, policy_profile_ref text NOT NULL,
           created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE case_grants (principal_id uuid REFERENCES principals(id),
           case_id uuid REFERENCES cases(id), can_write boolean NOT NULL,
           PRIMARY KEY(principal_id, case_id))""",
        "CREATE INDEX grants_case_idx ON case_grants(case_id)",
        """CREATE TABLE artifacts (id uuid PRIMARY KEY, sha256 char(64) NOT NULL UNIQUE,
           bytes bigint NOT NULL CHECK(bytes >= 0))""",
        """CREATE TABLE artifact_associations (id uuid PRIMARY KEY,
           case_id uuid NOT NULL REFERENCES cases(id), artifact_id uuid NOT NULL REFERENCES artifacts(id),
           source_id uuid NOT NULL, original_name text NOT NULL, media_type text NOT NULL,
           captured_at timestamptz, imported_at timestamptz NOT NULL DEFAULT now(),
           publication_status text NOT NULL CHECK(publication_status IN ('pending','committed','failed')),
           revision integer NOT NULL DEFAULT 1, stage_name text NOT NULL)""",
        "CREATE INDEX association_case_idx ON artifact_associations(case_id)",
        "CREATE INDEX association_blob_idx ON artifact_associations(artifact_id)",
        """CREATE TABLE idempotency (principal_id uuid NOT NULL REFERENCES principals(id),
           operation text NOT NULL, key text NOT NULL, body_hash char(64) NOT NULL,
           response jsonb NOT NULL, status integer NOT NULL,
           PRIMARY KEY(principal_id, operation, key))""",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    raise RuntimeError("Destructive downgrade is not provided; preserve data")
