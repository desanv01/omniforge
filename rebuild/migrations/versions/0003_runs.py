"""Persist harmless queued Run admission, ordered events and outbox intent only."""
from alembic import op

revision = "0003_runs"
down_revision = "0002_capture"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        """CREATE TABLE runs (
            id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES cases(id),
            requested_by uuid NOT NULL REFERENCES principals(id),
            schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
            revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
            kind text NOT NULL CHECK(kind='synthetic-read-only-v1'),
            status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','cancel_requested','canceled')),
            outcome text CHECK(outcome IS NULL OR octet_length(outcome)<=100),
            terminal_reason text CHECK(terminal_reason IS NULL OR octet_length(terminal_reason)<=500),
            input_refs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(input_refs)='array'
              AND jsonb_array_length(input_refs)<=32 AND octet_length(input_refs::text)<=32768),
            policy_version text NOT NULL CHECK(policy_version='local-read-only-v1'),
            scope_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(scope_snapshot)='object'
              AND octet_length(scope_snapshot::text)<=8192),
            budget jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(budget)='object'
              AND octet_length(budget::text)<=8192),
            usage jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(usage)='object'
              AND octet_length(usage::text)<=8192),
            provider_profile_ref jsonb CHECK(provider_profile_ref IS NULL OR
              (jsonb_typeof(provider_profile_ref)='object' AND octet_length(provider_profile_ref::text)<=4096)),
            output_refs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(output_refs)='array'
              AND jsonb_array_length(output_refs)<=64 AND octet_length(output_refs::text)<=32768),
            attempt_id uuid,
            fence bigint NOT NULL DEFAULT 0 CHECK(fence>=0),
            next_event_sequence bigint NOT NULL DEFAULT 2 CHECK(next_event_sequence>0),
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            cancel_requested_at timestamptz
        )""",
        "CREATE INDEX runs_case_id_idx ON runs(case_id,id)",
        "CREATE INDEX runs_requested_by_idx ON runs(requested_by)",
        """CREATE TABLE run_events (
            run_id uuid NOT NULL REFERENCES runs(id),
            sequence bigint NOT NULL CHECK(sequence>0),
            type text NOT NULL CHECK(octet_length(type) BETWEEN 1 AND 100),
            attempt_id uuid,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(payload)='object'
              AND octet_length(payload::text)<=8192),
            PRIMARY KEY(run_id,sequence)
        )""",
        """CREATE TABLE run_outbox (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runs(id),
            dispatch_key text NOT NULL UNIQUE CHECK(octet_length(dispatch_key) BETWEEN 1 AND 200),
            command text NOT NULL CHECK(command='start'),
            state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','suppressed')),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(payload)='object'
              AND octet_length(payload::text)<=8192),
            created_at timestamptz NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX run_outbox_run_idx ON run_outbox(run_id)",
        "CREATE INDEX run_outbox_state_id_idx ON run_outbox(state,id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    raise RuntimeError("Destructive downgrade is not provided; preserve run history")
