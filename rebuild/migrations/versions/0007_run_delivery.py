"""Immutable real-kind correlation and bounded async delivery generations."""
from alembic import op

revision = "0007_run_delivery"
down_revision = "0006_profile_bindings"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE run_outbox
      ADD COLUMN scheduler_kind text NOT NULL DEFAULT 'fake-v1' CHECK(scheduler_kind IN ('fake-v1','hatchet-v1')),
      ADD COLUMN dispatch_generation integer NOT NULL DEFAULT 0 CHECK(dispatch_generation BETWEEN 0 AND 1),
      ADD COLUMN candidate_ids uuid[] NOT NULL DEFAULT '{}',
      ADD CONSTRAINT delivery_candidate_shape CHECK(cardinality(candidate_ids)<=8
        AND (cardinality(candidate_ids)=0 OR array_ndims(candidate_ids)=1)
        AND array_position(candidate_ids,NULL) IS NULL),
      ADD CONSTRAINT delivery_fake_outbox_shape CHECK(scheduler_kind<>'fake-v1'
        OR (dispatch_generation=0 AND cardinality(candidate_ids)=0));

    CREATE TABLE run_scheduler_submissions (
      id uuid PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES runs(id),
      outbox_id uuid NOT NULL,
      generation integer NOT NULL CHECK(generation BETWEEN 0 AND 1),
      tenant_id uuid NOT NULL,
      workflow_id uuid NOT NULL,
      workflow_version_id uuid NOT NULL,
      workflow_name text NOT NULL CHECK(workflow_name ~ '^[A-Za-z0-9_.:-]{1,100}$'),
      namespace text NOT NULL CHECK(namespace ~ '^[A-Za-z0-9_.-]{1,64}$'),
      input_hash char(64) NOT NULL CHECK(input_hash ~ '^[0-9a-f]{64}$'),
      submission_hash char(64) NOT NULL CHECK(submission_hash ~ '^[0-9a-f]{64}$'),
      dispatch_identity char(64) NOT NULL CHECK(dispatch_identity ~ '^[0-9a-f]{64}$'),
      entry_revision integer NOT NULL CHECK(entry_revision>0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      recovery_attempt_id uuid,
      recovery_fence bigint,
      recovery_receipt_id uuid UNIQUE,
      recovery_at timestamptz,
      recovery_roots uuid[],
      recovery_proof_hash char(64) CHECK(recovery_proof_hash IS NULL OR recovery_proof_hash ~ '^[0-9a-f]{64}$'),
      UNIQUE(outbox_id,generation),
      UNIQUE(run_id,outbox_id,id),
      FOREIGN KEY(run_id,outbox_id) REFERENCES run_outbox(run_id,id),
      FOREIGN KEY(run_id,recovery_attempt_id,recovery_fence) REFERENCES run_attempts(run_id,id,fence),
      CHECK((generation=0 AND recovery_attempt_id IS NULL AND recovery_fence IS NULL
          AND recovery_receipt_id IS NULL AND recovery_at IS NULL AND recovery_roots IS NULL AND recovery_proof_hash IS NULL)
        OR (generation=1 AND recovery_attempt_id IS NOT NULL AND recovery_fence IS NOT NULL AND recovery_fence>0
          AND recovery_receipt_id IS NOT NULL AND recovery_at IS NOT NULL AND recovery_roots IS NOT NULL
          AND cardinality(recovery_roots) BETWEEN 1 AND 2 AND array_ndims(recovery_roots)=1
          AND array_position(recovery_roots,NULL) IS NULL AND recovery_proof_hash IS NOT NULL))
    );
    CREATE INDEX delivery_submission_run ON run_scheduler_submissions(run_id);
    CREATE INDEX delivery_submission_recovery ON run_scheduler_submissions(run_id,recovery_attempt_id,recovery_fence);

    ALTER TABLE run_scheduler_executions
      DROP CONSTRAINT run_scheduler_executions_scheduler_kind_check,
      ADD CONSTRAINT delivery_scheduler_kind CHECK(scheduler_kind IN ('fake-v1','hatchet-v1')),
      ADD COLUMN submission_id uuid,
      ADD COLUMN native_status text CHECK(native_status IS NULL OR native_status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
      ADD COLUMN task_ids uuid[],
      ADD COLUMN observed_at timestamptz,
      ADD CONSTRAINT delivery_mapping_owner UNIQUE(run_id,id),
      ADD CONSTRAINT delivery_submission_owner FOREIGN KEY(run_id,outbox_id,submission_id)
        REFERENCES run_scheduler_submissions(run_id,outbox_id,id),
      ADD CONSTRAINT delivery_mapping_shape CHECK
        ((scheduler_kind='fake-v1' AND submission_id IS NULL AND native_status IS NULL AND task_ids IS NULL AND observed_at IS NULL)
        OR (scheduler_kind='hatchet-v1' AND submission_id IS NOT NULL AND native_status IS NOT NULL AND task_ids IS NOT NULL
          AND observed_at IS NOT NULL AND cardinality(task_ids) BETWEEN 1 AND 50 AND array_ndims(task_ids)=1
          AND array_position(task_ids,NULL) IS NULL
          AND external_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          AND ((native_status IN ('QUEUED','RUNNING') AND observed_state='accepted')
            OR (native_status IN ('COMPLETED','FAILED','CANCELLED') AND observed_state='completed'))));
    CREATE INDEX delivery_task_ids ON run_scheduler_executions USING gin(task_ids) WHERE scheduler_kind='hatchet-v1';

    ALTER TABLE run_attempts
      ADD COLUMN execution_id uuid,
      ADD COLUMN worker_instance_id uuid,
      ADD CONSTRAINT delivery_attempt_pair CHECK((execution_id IS NULL)=(worker_instance_id IS NULL)),
      ADD CONSTRAINT delivery_attempt_owner FOREIGN KEY(run_id,execution_id) REFERENCES run_scheduler_executions(run_id,id);
    CREATE INDEX delivery_attempt_execution ON run_attempts(run_id,execution_id);

    CREATE FUNCTION guard_run_scheduler_submission() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE prior run_scheduler_submissions%ROWTYPE;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Scheduler submission history is immutable' USING ERRCODE='23514';
      END IF;
      IF NEW.generation=1 THEN
        SELECT * INTO prior FROM run_scheduler_submissions WHERE outbox_id=NEW.outbox_id AND generation=0;
        IF NOT FOUND OR
          ROW(NEW.run_id,NEW.tenant_id,NEW.workflow_id,NEW.workflow_version_id,NEW.workflow_name,NEW.namespace,NEW.input_hash)
          IS DISTINCT FROM ROW(prior.run_id,prior.tenant_id,prior.workflow_id,prior.workflow_version_id,prior.workflow_name,prior.namespace,prior.input_hash) THEN
          RAISE EXCEPTION 'Recovery submission binding conflicts' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER delivery_submission_guard BEFORE INSERT OR UPDATE OR DELETE ON run_scheduler_submissions
      FOR EACH ROW EXECUTE FUNCTION guard_run_scheduler_submission();

    CREATE FUNCTION guard_run_delivery_mapping() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR
        ROW(NEW.id,NEW.run_id,NEW.outbox_id,NEW.scheduler_kind,NEW.external_id,NEW.submission_id,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.outbox_id,OLD.scheduler_kind,OLD.external_id,OLD.submission_id,OLD.created_at) THEN
        RAISE EXCEPTION 'Scheduler mapping identity is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER delivery_mapping_guard BEFORE UPDATE OR DELETE ON run_scheduler_executions
      FOR EACH ROW EXECUTE FUNCTION guard_run_delivery_mapping();

    CREATE FUNCTION guard_run_delivery_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE removed uuid;
    BEGIN
      IF NEW.dispatch_count<OLD.dispatch_count OR NEW.reconcile_count<OLD.reconcile_count OR
        NEW.dispatch_generation<OLD.dispatch_generation OR
        ROW(NEW.id,NEW.run_id,NEW.dispatch_key,NEW.command,NEW.payload,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.dispatch_key,OLD.command,OLD.payload,OLD.created_at) THEN
        RAISE EXCEPTION 'Outbox identity and counters cannot be reset' USING ERRCODE='23514';
      END IF;
      IF NEW.scheduler_kind<>OLD.scheduler_kind AND NOT
        (OLD.scheduler_kind='fake-v1' AND NEW.scheduler_kind='hatchet-v1' AND OLD.dispatch_count=0
          AND OLD.reconcile_count=0 AND OLD.dispatch_generation=0 AND NEW.dispatch_generation=0) THEN
        RAISE EXCEPTION 'Scheduler kind cannot be rebound' USING ERRCODE='23514';
      END IF;
      FOR removed IN SELECT unnest(OLD.candidate_ids) EXCEPT SELECT unnest(NEW.candidate_ids) LOOP
        IF NOT EXISTS (SELECT 1 FROM run_scheduler_executions e WHERE e.run_id=NEW.run_id
          AND e.outbox_id=NEW.id AND e.scheduler_kind='hatchet-v1' AND e.external_id=removed::text) THEN
          RAISE EXCEPTION 'Unverified candidate cannot be discarded' USING ERRCODE='23514';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    CREATE TRIGGER delivery_outbox_guard BEFORE UPDATE ON run_outbox
      FOR EACH ROW EXECUTE FUNCTION guard_run_delivery_outbox();
    """)


def downgrade():
    raise RuntimeError("Forward only; preserve scheduler delivery history")
