"""Additive diagnostic operation/round journal. SOURCE ONLY in OF-012P-JOURNAL-A."""
from alembic import op

revision = "0009_provider_diagnostics"
down_revision = "0008_run_cancellation"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE provider_diagnostics (
      operation_id uuid PRIMARY KEY,
      invocation_id uuid NOT NULL UNIQUE,
      invocation_generation integer NOT NULL CHECK(invocation_generation>0),
      bootstrap_fingerprint char(64) NOT NULL CHECK(bootstrap_fingerprint ~ '^[0-9a-f]{64}$'),
      deadline_identity uuid NOT NULL,
      deadline_revision integer NOT NULL CHECK(deadline_revision>0),
      principal_id uuid NOT NULL REFERENCES principals(id),
      case_id uuid NOT NULL REFERENCES cases(id),
      profile_id uuid NOT NULL,
      profile_revision integer NOT NULL,
      fingerprint char(64) NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
      budget jsonb NOT NULL CHECK(jsonb_typeof(budget)='object' AND octet_length(budget::text)<=2048),
      expires_at timestamptz NOT NULL,
      capability_hash char(64) NOT NULL UNIQUE CHECK(capability_hash ~ '^[0-9a-f]{64}$'),
      state text NOT NULL DEFAULT 'open' CHECK(state IN ('open','stopped')),
      stop_reason text CHECK(stop_reason IN ('canceled','deadline','durability','authority','interrupted','budget','protocol')),
      candidate_digest char(64) CHECK(candidate_digest ~ '^[0-9a-f]{64}$'),
      candidate_at timestamptz,
      settlement_digest char(64) CHECK(settlement_digest ~ '^[0-9a-f]{64}$'),
      settlement_cutoff timestamptz,
      settled_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      FOREIGN KEY(profile_id,profile_revision,case_id) REFERENCES provider_profile_versions(profile_id,revision,case_id),
      CHECK((state='open')=(stop_reason IS NULL)),
      CHECK((candidate_digest IS NULL)=(candidate_at IS NULL)),
      CHECK((settlement_digest IS NULL)=(settlement_cutoff IS NULL)),
      CHECK((settlement_digest IS NULL)=(settled_at IS NULL)),
      CHECK(settlement_cutoff IS NULL OR settlement_cutoff<=expires_at+interval '4 seconds')
    );
    CREATE TABLE provider_diagnostic_rounds (
      operation_id uuid NOT NULL REFERENCES provider_diagnostics(operation_id),
      round_seq integer NOT NULL CHECK(round_seq BETWEEN 1 AND 2),
      payload_sha256 char(64) NOT NULL CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
      input_estimate integer NOT NULL CHECK(input_estimate BETWEEN 1 AND 32768),
      output_max integer NOT NULL CHECK(output_max BETWEEN 1 AND 512),
      reservation_digest char(64) NOT NULL CHECK(reservation_digest ~ '^[0-9a-f]{64}$'),
      reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      input_tokens integer CHECK(input_tokens BETWEEN 0 AND 1000000),
      output_tokens integer CHECK(output_tokens BETWEEN 0 AND 1000000),
      provenance text CHECK(provenance IN ('provider_reported','absent')),
      safe_outcome text CHECK(safe_outcome IN ('response_received','invalid_response','transport_failed')),
      charged_input_tokens integer CHECK(charged_input_tokens BETWEEN 0 AND 1000000),
      charged_output_tokens integer CHECK(charged_output_tokens BETWEEN 0 AND 1000000),
      observation_digest char(64) CHECK(observation_digest ~ '^[0-9a-f]{64}$'),
      observed_at timestamptz,
      PRIMARY KEY(operation_id,round_seq),
      CHECK((observation_digest IS NULL AND input_tokens IS NULL AND output_tokens IS NULL
          AND provenance IS NULL AND safe_outcome IS NULL AND charged_input_tokens IS NULL
          AND charged_output_tokens IS NULL AND observed_at IS NULL)
        OR (observation_digest IS NOT NULL AND observed_at IS NOT NULL AND provenance IS NOT NULL
          AND safe_outcome IS NOT NULL AND charged_input_tokens IS NOT NULL AND charged_output_tokens IS NOT NULL
          AND ((provenance='absent')=(input_tokens IS NULL AND output_tokens IS NULL))
          AND charged_input_tokens=GREATEST(input_estimate,COALESCE(input_tokens,0))
          AND charged_output_tokens=GREATEST(output_max,COALESCE(output_tokens,0))))
    );
    CREATE FUNCTION guard_provider_diagnostic_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Diagnostic history retained' USING ERRCODE='23514'; END IF;
      IF TG_TABLE_NAME='provider_diagnostics' THEN
        IF NEW.candidate_digest IS NOT NULL AND OLD.candidate_digest IS NULL THEN
          IF OLD.state<>'open' OR NOT EXISTS(SELECT 1 FROM provider_diagnostic_rounds WHERE operation_id=NEW.operation_id)
            OR EXISTS(SELECT 1 FROM provider_diagnostic_rounds WHERE operation_id=NEW.operation_id AND observation_digest IS NULL) THEN
            RAISE EXCEPTION 'Candidate needs nonempty observed rounds' USING ERRCODE='23514';
          END IF;
        END IF;
        IF ROW(NEW.operation_id,NEW.invocation_id,NEW.invocation_generation,NEW.bootstrap_fingerprint,
          NEW.deadline_identity,NEW.deadline_revision,NEW.principal_id,NEW.case_id,NEW.profile_id,
          NEW.profile_revision,NEW.fingerprint,NEW.budget,NEW.expires_at,NEW.capability_hash,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.operation_id,OLD.invocation_id,OLD.invocation_generation,OLD.bootstrap_fingerprint,
          OLD.deadline_identity,OLD.deadline_revision,OLD.principal_id,OLD.case_id,OLD.profile_id,
          OLD.profile_revision,OLD.fingerprint,OLD.budget,OLD.expires_at,OLD.capability_hash,OLD.created_at)
          OR (OLD.state='stopped' AND ROW(NEW.state,NEW.stop_reason) IS DISTINCT FROM ROW(OLD.state,OLD.stop_reason))
          OR (OLD.candidate_digest IS NOT NULL AND ROW(NEW.candidate_digest,NEW.candidate_at) IS DISTINCT FROM ROW(OLD.candidate_digest,OLD.candidate_at))
          OR (OLD.settlement_digest IS NOT NULL AND ROW(NEW.settlement_digest,NEW.settlement_cutoff,NEW.settled_at) IS DISTINCT FROM ROW(OLD.settlement_digest,OLD.settlement_cutoff,OLD.settled_at)) THEN
          RAISE EXCEPTION 'Diagnostic identity immutable' USING ERRCODE='23514';
        END IF;
      ELSE
        IF ROW(NEW.operation_id,NEW.round_seq,NEW.payload_sha256,NEW.input_estimate,NEW.output_max,NEW.reservation_digest,NEW.reserved_at)
          IS DISTINCT FROM ROW(OLD.operation_id,OLD.round_seq,OLD.payload_sha256,OLD.input_estimate,OLD.output_max,OLD.reservation_digest,OLD.reserved_at)
          OR (OLD.observation_digest IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
          RAISE EXCEPTION 'Diagnostic round immutable' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER diagnostic_history BEFORE UPDATE OR DELETE ON provider_diagnostics
      FOR EACH ROW EXECUTE FUNCTION guard_provider_diagnostic_history();
    CREATE TRIGGER diagnostic_round_history BEFORE UPDATE OR DELETE ON provider_diagnostic_rounds
      FOR EACH ROW EXECUTE FUNCTION guard_provider_diagnostic_history();
    """)


def downgrade():
    raise RuntimeError("Forward only; retain diagnostic history")
