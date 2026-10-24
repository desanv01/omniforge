"""Append-only case-scoped metadata; enrollment and credential binding deferred."""
from alembic import op

revision = "0005_provider_profiles"
down_revision = "0004_run_execution"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE provider_profile_versions (
      profile_id uuid NOT NULL, revision integer NOT NULL CHECK (revision > 0),
      case_id uuid NOT NULL REFERENCES cases(id),
      created_by uuid NOT NULL REFERENCES principals(id),
      schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version=1),
      label text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
      endpoint text NOT NULL CHECK (endpoint='https://api.deepseek.com/chat/completions'),
      model text NOT NULL CHECK (length(model) BETWEEN 1 AND 120 AND model ~ '^[ -~]+$' AND model=btrim(model)),
      calls integer NOT NULL CHECK (calls BETWEEN 1 AND 16),
      input_tokens integer NOT NULL CHECK (input_tokens BETWEEN 1 AND 1000000),
      output_tokens integer NOT NULL CHECK (output_tokens BETWEEN 1 AND 100000),
      wall_seconds integer NOT NULL CHECK (wall_seconds BETWEEN 1 AND 300),
      tool_bytes integer NOT NULL CHECK (tool_bytes BETWEEN 0 AND 1048576),
      enabled boolean NOT NULL DEFAULT false CHECK (NOT enabled),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(profile_id,revision)
    );
    CREATE INDEX provider_profile_case_current ON provider_profile_versions(case_id,profile_id,revision DESC);
    CREATE INDEX provider_profile_creator ON provider_profile_versions(created_by);
    CREATE FUNCTION guard_provider_profile_history() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE prior provider_profile_versions%ROWTYPE;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Profile history is append only' USING ERRCODE='23514';
      END IF;
      PERFORM pg_advisory_xact_lock(hashtextextended(NEW.profile_id::text, 12));
      SELECT * INTO prior FROM provider_profile_versions WHERE profile_id=NEW.profile_id ORDER BY revision DESC LIMIT 1;
      IF FOUND THEN
        IF NEW.case_id <> prior.case_id OR NEW.revision <> prior.revision+1 THEN
          RAISE EXCEPTION 'Profile identity or revision conflict' USING ERRCODE='23514';
        END IF;
      ELSIF NEW.revision <> 1 THEN
        RAISE EXCEPTION 'Initial revision must be one' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER provider_profile_history BEFORE INSERT OR UPDATE OR DELETE ON provider_profile_versions
      FOR EACH ROW EXECUTE FUNCTION guard_provider_profile_history();
    """)


def downgrade():
    raise RuntimeError("Forward only; preserve profile history")
