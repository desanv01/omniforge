"""Fresh operation-bound enrollment with immutable profile binding history."""
from alembic import op

revision = "0006_profile_bindings"
down_revision = "0005_provider_profiles"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE provider_profile_versions ADD CONSTRAINT profile_version_case UNIQUE(profile_id,revision,case_id);
    CREATE TABLE provider_enrollments (
      operation_id uuid PRIMARY KEY,
      principal_id uuid NOT NULL REFERENCES principals(id),
      case_id uuid NOT NULL REFERENCES cases(id),
      profile_id uuid NOT NULL,
      credential_ref text NOT NULL UNIQUE CHECK
        (credential_ref ~ '^wincred:omniforge:v1:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
      expected_revision integer NOT NULL CHECK(expected_revision > 0 AND expected_revision < 2147483647),
      state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','attached','unresolved')),
      attached_revision integer,
      failure_code text CHECK(failure_code IN ('enrollment_incomplete')),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      settled_at timestamptz,
      FOREIGN KEY(profile_id,expected_revision,case_id) REFERENCES provider_profile_versions(profile_id,revision,case_id),
      UNIQUE(operation_id,principal_id,case_id,profile_id,credential_ref,expected_revision),
      CHECK ((state='pending' AND attached_revision IS NULL AND failure_code IS NULL AND settled_at IS NULL)
          OR (state='attached' AND attached_revision IS NOT NULL AND attached_revision=expected_revision+1 AND failure_code IS NULL AND settled_at IS NOT NULL)
          OR (state='unresolved' AND attached_revision IS NULL AND failure_code IS NOT NULL AND settled_at IS NOT NULL))
    );
    CREATE INDEX enrollment_profile ON provider_enrollments(profile_id,created_at DESC,operation_id);
    CREATE INDEX enrollment_case ON provider_enrollments(case_id);
    CREATE INDEX enrollment_principal ON provider_enrollments(principal_id);
    ALTER TABLE provider_profile_versions
      DROP CONSTRAINT provider_profile_versions_enabled_check,
      ADD COLUMN credential_ref text,
      ADD COLUMN binding_operation_id uuid,
      ADD COLUMN binding_principal_id uuid,
      ADD COLUMN binding_expected_revision integer,
      ADD CONSTRAINT profile_binding_shape CHECK
        ((credential_ref IS NULL AND binding_operation_id IS NULL AND binding_principal_id IS NULL AND binding_expected_revision IS NULL AND NOT enabled)
         OR (credential_ref IS NOT NULL AND binding_operation_id IS NOT NULL AND binding_principal_id IS NOT NULL AND binding_expected_revision IS NOT NULL)),
      ADD CONSTRAINT profile_complete_binding FOREIGN KEY
        (binding_operation_id,binding_principal_id,case_id,profile_id,credential_ref,binding_expected_revision)
        REFERENCES provider_enrollments(operation_id,principal_id,case_id,profile_id,credential_ref,expected_revision);

    CREATE OR REPLACE FUNCTION guard_provider_profile_history() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE prior provider_profile_versions%ROWTYPE; enrollment provider_enrollments%ROWTYPE;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Profile history is append only' USING ERRCODE='23514';
      END IF;
      PERFORM pg_advisory_xact_lock(hashtextextended(NEW.profile_id::text,12));
      SELECT * INTO prior FROM provider_profile_versions WHERE profile_id=NEW.profile_id ORDER BY revision DESC LIMIT 1;
      IF FOUND THEN
        IF NEW.case_id <> prior.case_id OR NEW.revision <> prior.revision+1 THEN
          RAISE EXCEPTION 'Profile identity or revision conflict' USING ERRCODE='23514';
        END IF;
        IF ROW(NEW.credential_ref,NEW.binding_operation_id,NEW.binding_principal_id,NEW.binding_expected_revision)
            IS DISTINCT FROM ROW(prior.credential_ref,prior.binding_operation_id,prior.binding_principal_id,prior.binding_expected_revision) THEN
          SELECT * INTO enrollment FROM provider_enrollments WHERE operation_id=NEW.binding_operation_id;
          IF NOT FOUND OR enrollment.state <> 'pending' OR NEW.enabled OR
             ROW(enrollment.principal_id,enrollment.case_id,enrollment.profile_id,enrollment.credential_ref,enrollment.expected_revision)
             IS DISTINCT FROM ROW(NEW.created_by,NEW.case_id,NEW.profile_id,NEW.credential_ref,prior.revision) OR
             NEW.binding_principal_id <> enrollment.principal_id OR NEW.binding_expected_revision <> enrollment.expected_revision THEN
            RAISE EXCEPTION 'Invalid fresh profile attachment' USING ERRCODE='23514';
          END IF;
        END IF;
      ELSIF NEW.revision <> 1 OR NEW.credential_ref IS NOT NULL OR NEW.enabled THEN
        RAISE EXCEPTION 'Initial profile must be unconfigured' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;

    CREATE FUNCTION guard_provider_enrollment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='INSERT' THEN
        IF NEW.state <> 'pending' THEN
          RAISE EXCEPTION 'Enrollment must start pending' USING ERRCODE='23514';
        END IF;
      ELSIF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Enrollment history is retained' USING ERRCODE='23514';
      ELSIF OLD.state <> 'pending' OR NEW.state NOT IN ('attached','unresolved') OR
        ROW(NEW.operation_id,NEW.principal_id,NEW.case_id,NEW.profile_id,NEW.credential_ref,NEW.expected_revision,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.operation_id,OLD.principal_id,OLD.case_id,OLD.profile_id,OLD.credential_ref,OLD.expected_revision,OLD.created_at) THEN
        RAISE EXCEPTION 'Enrollment binding is immutable' USING ERRCODE='23514';
      END IF;
      IF NEW.state='attached' AND NOT EXISTS (
        SELECT 1 FROM provider_profile_versions p WHERE p.profile_id=NEW.profile_id AND p.revision=NEW.attached_revision
          AND p.case_id=NEW.case_id AND p.created_by=NEW.principal_id AND NOT p.enabled
          AND p.credential_ref=NEW.credential_ref AND p.binding_operation_id=NEW.operation_id
          AND p.binding_principal_id=NEW.principal_id AND p.binding_expected_revision=NEW.expected_revision) THEN
        RAISE EXCEPTION 'Enrollment lacks exact attached revision' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER provider_enrollment_guard BEFORE INSERT OR UPDATE OR DELETE ON provider_enrollments
      FOR EACH ROW EXECUTE FUNCTION guard_provider_enrollment();

    CREATE FUNCTION check_committed_profile_binding() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.credential_ref IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM provider_enrollments e WHERE e.operation_id=NEW.binding_operation_id
          AND e.principal_id=NEW.binding_principal_id AND e.case_id=NEW.case_id AND e.profile_id=NEW.profile_id
          AND e.credential_ref=NEW.credential_ref AND e.expected_revision=NEW.binding_expected_revision
          AND e.state='attached' AND e.attached_revision <= NEW.revision) THEN
        RAISE EXCEPTION 'Profile binding is not attached' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE CONSTRAINT TRIGGER provider_binding_committed AFTER INSERT ON provider_profile_versions
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_committed_profile_binding();
    """)


def downgrade():
    raise RuntimeError("Forward only; retain enrollment history")
