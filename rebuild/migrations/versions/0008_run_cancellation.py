"""Durable active cancellation and cleanup-only receipt authority."""
from alembic import op

revision = "0008_run_cancellation"
down_revision = "0007_run_delivery"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE runs
      ADD COLUMN cancellation_id uuid,
      ADD COLUMN cancel_generation integer NOT NULL DEFAULT 0 CHECK(cancel_generation BETWEEN 0 AND 1),
      ADD COLUMN cleanup_status text NOT NULL DEFAULT 'not_requested'
        CHECK(cleanup_status IN ('not_requested','pending','succeeded','failed','unknown')),
      ADD CONSTRAINT cancellation_run_case UNIQUE(id,case_id),
      ADD CONSTRAINT cancellation_run_shape CHECK
        ((cancellation_id IS NULL AND cancel_generation=0 AND cleanup_status='not_requested')
         OR (cancellation_id IS NOT NULL AND cancel_generation=1 AND cleanup_status<>'not_requested'));

    CREATE TABLE run_cancellations (
      id uuid PRIMARY KEY,
      run_id uuid NOT NULL UNIQUE,
      case_id uuid NOT NULL,
      requested_by uuid NOT NULL REFERENCES principals(id),
      generation integer NOT NULL CHECK(generation=1),
      request_revision integer NOT NULL CHECK(request_revision>0),
      request_snapshot jsonb NOT NULL CHECK(jsonb_typeof(request_snapshot)='object'
        AND octet_length(request_snapshot::text)<=65536),
      state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','settled','unresolved')),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE(run_id,id,generation),
      FOREIGN KEY(run_id,case_id) REFERENCES runs(id,case_id)
    );
    CREATE INDEX cancellation_requester ON run_cancellations(requested_by);
    CREATE INDEX cancellation_case ON run_cancellations(case_id);
    ALTER TABLE runs ADD CONSTRAINT cancellation_current_owner
      FOREIGN KEY(id,cancellation_id,cancel_generation) REFERENCES run_cancellations(run_id,id,generation);

    CREATE TABLE run_cancel_targets (
      id uuid PRIMARY KEY,
      run_id uuid NOT NULL,
      cancel_id uuid NOT NULL,
      generation integer NOT NULL CHECK(generation=1),
      execution_id uuid NOT NULL,
      original_attempt_id uuid,
      original_fence bigint,
      worker_instance_id uuid,
      task_ids uuid[],
      cleanup_credential_hash char(64) UNIQUE,
      command_key text NOT NULL UNIQUE CHECK(command_key ~ '^[A-Za-z0-9_.:-]{1,200}$'),
      command_state text NOT NULL DEFAULT 'pending'
        CHECK(command_state IN ('pending','claimed','acknowledged','reconcile_required')),
      cancel_count integer NOT NULL DEFAULT 0 CHECK(cancel_count BETWEEN 0 AND 2),
      lookup_count integer NOT NULL DEFAULT 0 CHECK(lookup_count BETWEEN 0 AND 2),
      claim_token uuid,
      claim_until timestamptz,
      last_error_code text CHECK(last_error_code IS NULL OR last_error_code ~ '^[a-z0-9_]{1,100}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE(cancel_id,execution_id),
      UNIQUE(run_id,cancel_id,id,execution_id,cleanup_credential_hash,worker_instance_id),
      FOREIGN KEY(run_id,cancel_id,generation) REFERENCES run_cancellations(run_id,id,generation),
      FOREIGN KEY(run_id,execution_id) REFERENCES run_scheduler_executions(run_id,id),
      FOREIGN KEY(run_id,original_attempt_id,original_fence) REFERENCES run_attempts(run_id,id,fence),
      CHECK((original_attempt_id IS NULL AND original_fence IS NULL)
        OR (original_attempt_id IS NOT NULL AND original_fence IS NOT NULL AND original_fence>0)),
      CHECK(cleanup_credential_hash IS NULL OR (cleanup_credential_hash ~ '^[0-9a-f]{64}$' AND worker_instance_id IS NOT NULL)),
      CHECK((claim_token IS NULL)=(claim_until IS NULL)),
      CHECK(task_ids IS NULL OR (cardinality(task_ids) BETWEEN 1 AND 50 AND array_ndims(task_ids)=1
        AND array_position(task_ids,NULL) IS NULL))
    );
    CREATE INDEX cancellation_target_run ON run_cancel_targets(run_id,cancel_id);
    CREATE INDEX cancellation_target_execution ON run_cancel_targets(run_id,execution_id);
    CREATE INDEX cancellation_target_attempt ON run_cancel_targets(run_id,original_attempt_id,original_fence);
    CREATE INDEX cancellation_target_command ON run_cancel_targets(command_state,id);

    CREATE TABLE run_cancel_receipts (
      id uuid PRIMARY KEY,
      run_id uuid NOT NULL,
      cancel_id uuid NOT NULL,
      target_id uuid NOT NULL UNIQUE,
      execution_id uuid NOT NULL,
      generation integer NOT NULL CHECK(generation=1),
      credential_hash char(64) NOT NULL CHECK(credential_hash ~ '^[0-9a-f]{64}$'),
      worker_instance_id uuid NOT NULL,
      result text NOT NULL CHECK(result IN ('succeeded','failed','unknown')),
      receipt_hash char(64) NOT NULL CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
      task_ids uuid[],
      received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      FOREIGN KEY(run_id,cancel_id,generation) REFERENCES run_cancellations(run_id,id,generation),
      FOREIGN KEY(run_id,cancel_id,target_id,execution_id,credential_hash,worker_instance_id)
        REFERENCES run_cancel_targets(run_id,cancel_id,id,execution_id,cleanup_credential_hash,worker_instance_id),
      CHECK(task_ids IS NULL OR (cardinality(task_ids) BETWEEN 1 AND 50 AND array_ndims(task_ids)=1
        AND array_position(task_ids,NULL) IS NULL))
    );
    CREATE INDEX cancellation_receipt_run ON run_cancel_receipts(run_id,cancel_id);

    CREATE FUNCTION guard_run_cancellation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR
        ROW(NEW.id,NEW.run_id,NEW.case_id,NEW.requested_by,NEW.generation,NEW.request_revision,NEW.request_snapshot,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.case_id,OLD.requested_by,OLD.generation,OLD.request_revision,OLD.request_snapshot,OLD.created_at) THEN
        RAISE EXCEPTION 'Cancellation request history is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cancellation_request_guard BEFORE UPDATE OR DELETE ON run_cancellations
      FOR EACH ROW EXECUTE FUNCTION guard_run_cancellation();

    CREATE FUNCTION guard_run_cancel_target() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE kind text;
    BEGIN
      IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Cancellation targets are retained' USING ERRCODE='23514';
      END IF;
      SELECT scheduler_kind INTO kind FROM run_scheduler_executions WHERE id=NEW.execution_id AND run_id=NEW.run_id;
      IF (kind='hatchet-v1' AND NEW.task_ids IS NULL) OR (kind='fake-v1' AND NEW.task_ids IS NOT NULL) THEN
        RAISE EXCEPTION 'Cancellation task snapshot conflicts' USING ERRCODE='23514';
      END IF;
      IF TG_OP='UPDATE' THEN
        IF ROW(NEW.id,NEW.run_id,NEW.cancel_id,NEW.generation,NEW.execution_id,NEW.original_attempt_id,NEW.original_fence,NEW.command_key,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.cancel_id,OLD.generation,OLD.execution_id,OLD.original_attempt_id,OLD.original_fence,OLD.command_key,OLD.created_at)
          OR NEW.cancel_count<OLD.cancel_count OR NEW.lookup_count<OLD.lookup_count
          OR (OLD.worker_instance_id IS NOT NULL AND NEW.worker_instance_id IS DISTINCT FROM OLD.worker_instance_id)
          OR (OLD.worker_instance_id IS NULL AND NEW.worker_instance_id IS NOT NULL AND NEW.cleanup_credential_hash IS NULL)
          OR (OLD.cleanup_credential_hash IS NOT NULL AND
            ROW(NEW.cleanup_credential_hash,NEW.task_ids) IS DISTINCT FROM ROW(OLD.cleanup_credential_hash,OLD.task_ids))
          OR (OLD.task_ids IS NOT NULL AND (NEW.task_ids IS NULL OR NOT NEW.task_ids @> OLD.task_ids)) THEN
          RAISE EXCEPTION 'Cancellation target identity cannot be reset' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cancellation_target_guard BEFORE INSERT OR UPDATE OR DELETE ON run_cancel_targets
      FOR EACH ROW EXECUTE FUNCTION guard_run_cancel_target();

    CREATE FUNCTION guard_run_cancel_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE expected_tasks uuid[];
    BEGIN
      IF TG_OP<>'INSERT' THEN
        RAISE EXCEPTION 'Cleanup receipts are immutable' USING ERRCODE='23514';
      END IF;
      SELECT task_ids INTO expected_tasks FROM run_cancel_targets WHERE id=NEW.target_id;
      IF NEW.task_ids IS DISTINCT FROM expected_tasks THEN
        RAISE EXCEPTION 'Cleanup receipt task snapshot conflicts' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cancellation_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON run_cancel_receipts
      FOR EACH ROW EXECUTE FUNCTION guard_run_cancel_receipt();

    CREATE FUNCTION guard_run_cancel_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.cancellation_id IS NOT NULL AND
        ROW(NEW.cancellation_id,NEW.cancel_generation,NEW.case_id)
        IS DISTINCT FROM ROW(OLD.cancellation_id,OLD.cancel_generation,OLD.case_id) THEN
        RAISE EXCEPTION 'Current cancellation identity is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cancellation_identity_guard BEFORE UPDATE ON runs
      FOR EACH ROW EXECUTE FUNCTION guard_run_cancel_identity();
    """)


def downgrade():
    raise RuntimeError("Forward only; preserve cancellation and cleanup history")
