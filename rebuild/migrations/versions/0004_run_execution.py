"""Fenced synthetic attempts/outputs and explicitly scoped fake-scheduler mappings."""
from alembic import op

revision = "0004_run_execution"
down_revision = "0003_runs"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        "ALTER TABLE runs DROP CONSTRAINT runs_status_check",
        """ALTER TABLE runs ADD CONSTRAINT runs_execution_status_check CHECK(status IN
            ('queued','claimed','running','cancel_requested','succeeded','failed','canceled','interrupted','uncertain'))""",
        "ALTER TABLE run_outbox DROP CONSTRAINT run_outbox_state_check",
        """ALTER TABLE run_outbox ADD CONSTRAINT run_outbox_execution_state_check CHECK(state IN
            ('pending','suppressed','claimed','acknowledged','reconcile_required'))""",
        """ALTER TABLE run_outbox
            ADD COLUMN claim_token uuid,
            ADD COLUMN claim_until timestamptz,
            ADD COLUMN dispatch_count integer NOT NULL DEFAULT 0 CHECK(dispatch_count BETWEEN 0 AND 2),
            ADD COLUMN reconcile_count integer NOT NULL DEFAULT 0 CHECK(reconcile_count BETWEEN 0 AND 2),
            ADD COLUMN last_error_code text CHECK(last_error_code IS NULL OR
                last_error_code ~ '^[a-z0-9_]{1,100}$'),
            ADD CONSTRAINT run_outbox_claim_pair CHECK((claim_token IS NULL)=(claim_until IS NULL)),
            ADD CONSTRAINT run_outbox_run_id_unique UNIQUE(run_id,id)""",
        """CREATE TABLE run_attempts (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runs(id),
            fence bigint NOT NULL CHECK(fence>0),
            state text NOT NULL CHECK(state IN ('running','completed','expired','failed','uncertain')),
            worker_id text NOT NULL CHECK(octet_length(worker_id) BETWEEN 1 AND 100),
            lease_expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            finished_at timestamptz,
            UNIQUE(run_id,fence),
            UNIQUE(run_id,id),
            UNIQUE(run_id,id,fence)
        )""",
        "CREATE INDEX run_attempts_lease_idx ON run_attempts(state,lease_expires_at)",
        """ALTER TABLE runs ADD CONSTRAINT runs_current_attempt_owner_fk
            FOREIGN KEY(id,attempt_id) REFERENCES run_attempts(run_id,id)""",
        """ALTER TABLE run_events ADD CONSTRAINT run_events_attempt_owner_fk
            FOREIGN KEY(run_id,attempt_id) REFERENCES run_attempts(run_id,id)""",
        """CREATE TABLE run_outputs (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runs(id),
            output_key text NOT NULL CHECK(octet_length(output_key) BETWEEN 1 AND 80),
            sha256 char(64) NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
            content jsonb NOT NULL CHECK(jsonb_typeof(content)='object' AND octet_length(content::text)<=8192),
            attempt_id uuid NOT NULL,
            fence bigint NOT NULL CHECK(fence>0),
            expected_revision integer NOT NULL CHECK(expected_revision>0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(run_id,output_key),
            FOREIGN KEY(run_id,attempt_id,fence) REFERENCES run_attempts(run_id,id,fence)
        )""",
        "CREATE INDEX run_outputs_attempt_idx ON run_outputs(run_id,attempt_id,fence)",
        """CREATE TABLE run_scheduler_executions (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runs(id),
            outbox_id uuid NOT NULL,
            scheduler_kind text NOT NULL DEFAULT 'fake-v1' CHECK(scheduler_kind='fake-v1'),
            external_id text NOT NULL CHECK(octet_length(external_id) BETWEEN 1 AND 100),
            observed_state text NOT NULL CHECK(observed_state IN ('accepted','completed')),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(scheduler_kind,external_id),
            FOREIGN KEY(run_id,outbox_id) REFERENCES run_outbox(run_id,id)
        )""",
        "CREATE INDEX run_scheduler_outbox_idx ON run_scheduler_executions(run_id,outbox_id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    raise RuntimeError("Destructive downgrade is not provided; preserve execution history")
