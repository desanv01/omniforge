package db

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/desanv01/omniforge/securitysource"
	"github.com/google/uuid"
)

var ErrDefenseExecutionNotFound = errors.New("Defense verification run not found")

type DefenseExecutionInput struct {
	SourceKind                string                     `json:"source_kind"`
	FileConfig                *securitysource.FileConfig `json:"file_config,omitempty"`
	SourceID                  int64                      `json:"source_id,string"`
	PlanRevision              int64                      `json:"plan_revision"`
	ExpectedEvidenceVersion   *int64                     `json:"expected_evidence_version"`
	ExpectedSourceFingerprint string                     `json:"expected_source_fingerprint"`
	BaselineID                *int64                     `json:"baseline_id,string,omitempty"`
	RemediationNote           string                     `json:"remediation_note"`
}

type DefenseExecution struct {
	ID                   int64                `json:"id,string"`
	FindingID            int64                `json:"finding_id,string"`
	SourceID             int64                `json:"source_id,string"`
	SourceKind           string               `json:"source_kind"`
	RetestID             int64                `json:"retest_id"`
	CorrelationID        string               `json:"correlation_id"`
	SourceRevision       int64                `json:"source_revision"`
	SourceSnapshot       json.RawMessage      `json:"source_snapshot"`
	DiagnosisSnapshot    json.RawMessage      `json:"diagnosis_snapshot,omitempty"`
	PlanSnapshot         DefensePlan          `json:"plan_snapshot"`
	EvidenceVersion      int64                `json:"evidence_version"`
	SourceFingerprint    string               `json:"source_fingerprint"`
	BaselineID           *int64               `json:"baseline_id,string,omitempty"`
	RemediationNote      string               `json:"remediation_note"`
	CreatedAt            time.Time            `json:"created_at"`
	Retest               *FindingRetest       `json:"retest"`
	Assessments          []*DefenseAssessment `json:"assessments"`
	State                string               `json:"state"`
	AssessmentsTruncated bool                 `json:"assessments_truncated"`
}

type DefenseAssessment struct {
	ID                int64                       `json:"id,string"`
	ExecutionID       int64                       `json:"execution_id,string"`
	Detection         string                      `json:"detection"`
	Prevention        string                      `json:"prevention"`
	Reasons           []string                    `json:"reasons"`
	Recommendations   []string                    `json:"recommendations"`
	Diagnostics       []securitysource.Diagnostic `json:"diagnostics"`
	Evidence          *securitysource.Evidence    `json:"evidence"`
	CreatedAt         time.Time                   `json:"created_at"`
	EventCount        int                         `json:"event_count"`
	AuditCount        int                         `json:"audit_count"`
	AlertCount        int                         `json:"alert_count"`
	EvidenceTruncated bool                        `json:"evidence_truncated"`
}

type DefenseComparison struct {
	Baseline   *DefenseExecution `json:"baseline"`
	Current    *DefenseExecution `json:"current"`
	Comparable bool              `json:"comparable"`
	Reasons    []string          `json:"reasons"`
}

const executionRetestSQL = `CASE WHEN e.retest_snapshot->>'status' IN ('completed','failed','stopped') THEN e.retest_snapshot ELSE COALESCE(to_jsonb(r)-'snapshot',e.retest_snapshot) END`

// Scope freshness also follows the actual target records, not just asset IDs.
// Only execution-relevant fields participate: discovery timestamps, constraint
// provenance and other mutable metadata must not invalidate an observation.
const executionCurrentScopeSQL = `jsonb_build_object('vulnclass',f.vulnclass,
 'assets',COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object('id',a.id,'type',a.type,'domain',a.domain,'ip',a.ip,'port',a.port,'url',a.url,'method',a.method)) ORDER BY a.id)
 FROM assets a WHERE f.asset_ids @> to_jsonb(ARRAY[a.id])),'[]'::jsonb),
 'constraints',COALESCE((SELECT jsonb_agg(jsonb_build_object('kind',c.kind,'text',c.text) ORDER BY c.kind,c.text)
 FROM task_constraints c JOIN tasks t ON t.exploration_id=c.exploration_id WHERE t.id=f.task_id),'[]'::jsonb))`

const executionSnapshotScopeSQL = `CASE WHEN jsonb_typeof(e.diagnosis_snapshot->'finding')='object'
 AND jsonb_typeof(e.diagnosis_snapshot->'assets')='array' AND jsonb_typeof(e.diagnosis_snapshot->'constraints')='array'
 THEN jsonb_build_object('vulnclass',e.diagnosis_snapshot#>'{finding,vulnclass}',
 'assets',COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object('id',a->'id','type',a->'type','domain',a->'domain','ip',a->'ip','port',a->'port','url',a->'url','method',a->'method')) ORDER BY (a->>'id')::bigint)
 FROM jsonb_array_elements(e.diagnosis_snapshot->'assets') a),'[]'::jsonb),
 'constraints',COALESCE((SELECT jsonb_agg(jsonb_build_object('kind',c->'kind','text',c->'text') ORDER BY c->>'kind',c->>'text')
 FROM jsonb_array_elements(e.diagnosis_snapshot->'constraints') c),'[]'::jsonb)) END`

const executionStateSQL = `CASE WHEN ((e.source_kind='file' AND e.source_id=0 AND e.source_revision=1 AND e.source_snapshot->>'kind'='file') OR (e.source_kind='splunk' AND s.enabled AND s.revision=e.source_revision AND s.config=e.source_snapshot->'config')) AND p.revision=(e.plan_snapshot->>'revision')::bigint AND f.evidence_version=e.evidence_version AND ` + defenseSourceFingerprintSQL + `=e.source_fingerprint AND ` + executionCurrentScopeSQL + `=` + executionSnapshotScopeSQL + ` THEN 'current' ELSE 'stale' END`
const executionSelect = `SELECT e.id,e.finding_id,e.source_id,e.source_kind,e.retest_id,e.correlation_id::text,e.source_revision,e.source_snapshot,e.diagnosis_snapshot,e.plan_snapshot,e.evidence_version,e.source_fingerprint,e.baseline_id,e.remediation_note,e.created_at,` + executionRetestSQL + `,` + executionStateSQL + `
 FROM finding_defense_executions e JOIN findings f ON f.id=e.finding_id
 LEFT JOIN finding_defense_plans p ON p.finding_id=f.id LEFT JOIN security_sources s ON s.id=e.source_id
 LEFT JOIN finding_retests r ON r.id=e.retest_id AND r.finding_id=e.finding_id `

func scanDefenseExecution(row interface{ Scan(...any) error }) (*DefenseExecution, error) {
	out := &DefenseExecution{Assessments: []*DefenseAssessment{}}
	var plan, retest []byte
	if err := row.Scan(&out.ID, &out.FindingID, &out.SourceID, &out.SourceKind, &out.RetestID, &out.CorrelationID, &out.SourceRevision, &out.SourceSnapshot, &out.DiagnosisSnapshot, &plan, &out.EvidenceVersion, &out.SourceFingerprint, &out.BaselineID, &out.RemediationNote, &out.CreatedAt, &retest, &out.State); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(plan, &out.PlanSnapshot); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(retest, &out.Retest); err != nil {
		return nil, err
	}
	if out.Retest != nil {
		out.Retest.Snapshot = nil
	}
	return out, nil
}

func scanDefenseAssessment(row interface{ Scan(...any) error }) (*DefenseAssessment, error) {
	out := &DefenseAssessment{}
	var reasons, recommendations, diagnostics, evidence []byte
	if err := row.Scan(&out.ID, &out.ExecutionID, &out.Detection, &out.Prevention, &reasons, &recommendations, &diagnostics, &evidence, &out.CreatedAt); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(reasons, &out.Reasons); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(recommendations, &out.Recommendations); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(diagnostics, &out.Diagnostics); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(evidence, &out.Evidence); err != nil {
		return nil, err
	}
	countDefenseEvidence(out)
	return out, nil
}

func loadDefenseAssessmentsTx(ctx context.Context, tx *sql.Tx, e *DefenseExecution, preview bool) error {
	query := `SELECT id,execution_id,detection,prevention,reasons,recommendations,diagnostics,evidence,created_at FROM finding_defense_assessments WHERE execution_id=$1 ORDER BY id DESC`
	if preview {
		query += ` LIMIT 6`
	}
	rows, err := tx.QueryContext(ctx, query, e.ID)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		if preview && len(e.Assessments) == 5 {
			e.AssessmentsTruncated = true
			break
		}
		a, err := scanDefenseAssessment(rows)
		if err != nil {
			return err
		}
		if preview {
			a = previewDefenseAssessment(a)
		}
		e.Assessments = append(e.Assessments, a)
	}
	return rows.Err()
}

func getDefenseExecutionTx(ctx context.Context, tx *sql.Tx, findingID, id int64) (*DefenseExecution, error) {
	e, err := getDefenseExecutionMetadataTx(ctx, tx, findingID, id)
	if err != nil {
		return nil, err
	}
	if err := loadDefenseAssessmentsTx(ctx, tx, e, false); err != nil {
		return nil, err
	}
	return e, nil
}

func getDefenseExecutionMetadataTx(ctx context.Context, tx *sql.Tx, findingID, id int64) (*DefenseExecution, error) {
	e, err := scanDefenseExecution(tx.QueryRowContext(ctx, executionSelect+`WHERE e.finding_id=$1 AND e.id=$2`, findingID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrDefenseExecutionNotFound
	}
	if err != nil {
		return nil, err
	}
	return e, nil
}

func createDefenseExecutionTx(ctx context.Context, tx *sql.Tx, findingID int64, retest *FindingRetest, in DefenseExecutionInput) (*DefenseExecution, error) {
	if retest == nil || retest.ID <= 0 || retest.FindingID != findingID || in.PlanRevision <= 0 || in.ExpectedEvidenceVersion == nil || *in.ExpectedEvidenceVersion < 0 {
		return nil, fmt.Errorf("%w: Please check execution input and proof version", ErrDefenseInvalid)
	}
	if in.SourceKind == "" {
		in.SourceKind = "splunk"
	}
	if in.SourceKind != "splunk" && in.SourceKind != "file" || in.SourceKind == "file" && (in.SourceID != 0 || in.FileConfig == nil) || in.SourceKind == "splunk" && (in.SourceID <= 0 || in.FileConfig != nil) {
		return nil, fmt.Errorf("%w: Please check the execution evidence source type and settings.", ErrDefenseInvalid)
	}
	var err error
	in.RemediationNote, err = defenseText(in.RemediationNote, "Description of improvement actions", 0, 8000)
	if err != nil {
		return nil, err
	}
	if in.BaselineID != nil && (*in.BaselineID <= 0 || in.RemediationNote == "") {
		return nil, fmt.Errorf("%w: Need to explain baseline implementation and improvement actions", ErrDefenseInvalid)
	}
	if err := LockFindingEvidenceTx(tx, findingID, nil); err != nil {
		return nil, err
	}
	state, err := findingDefenseTx(ctx, tx, findingID)
	if err != nil {
		return nil, err
	}
	if state.Plan == nil || state.Plan.Revision != in.PlanRevision || state.EvidenceVersion != *in.ExpectedEvidenceVersion || state.SourceFingerprint != in.ExpectedSourceFingerprint {
		return nil, ErrDefenseConflict
	}
	var source json.RawMessage
	var revision int64
	if in.SourceKind == "file" {
		config, err := securitysource.ValidateFileConfig(*in.FileConfig)
		if err != nil {
			return nil, fmt.Errorf("%w: %v", ErrDefenseInvalid, err)
		}
		revision = 1
		source, err = json.Marshal(map[string]any{"kind": "file", "name": config.Label, "config": config, "revision": revision})
		if err != nil {
			return nil, err
		}
	} else {
		var enabled, credentialSet bool
		err = tx.QueryRowContext(ctx, `SELECT jsonb_build_object('id',id::text,'name',name,'revision',revision,'config',config,'enabled',enabled,'credential_set',octet_length(secret_cipher)>0,'updated_at',updated_at),revision,enabled,octet_length(secret_cipher)>0 FROM security_sources WHERE id=$1 FOR SHARE`, in.SourceID).Scan(&source, &revision, &enabled, &credentialSet)
		if errors.Is(err, sql.ErrNoRows) {
			return nil, fmt.Errorf("%w: Evidence source not found", ErrDefenseInvalid)
		}
		if err != nil {
			return nil, err
		}
		if !enabled || !credentialSet {
			return nil, fmt.Errorf("%w: Requires an evidence source that is enabled and has credentials set", ErrDefenseInvalid)
		}
		var publicSource struct {
			Config securitysource.Config `json:"config"`
		}
		if err := json.Unmarshal(source, &publicSource); err != nil {
			return nil, err
		}
		if _, err := securitysource.Validate(publicSource.Config); err != nil {
			return nil, fmt.Errorf("%w: Please check your evidence source settings", ErrDefenseInvalid)
		}
	}
	if in.BaselineID != nil {
		baseline, err := getDefenseExecutionMetadataTx(ctx, tx, findingID, *in.BaselineID)
		if err != nil {
			return nil, err
		}
		var assessed bool
		if err := tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM finding_defense_assessments WHERE execution_id=$1)`, baseline.ID).Scan(&assessed); err != nil {
			return nil, err
		}
		if baseline.Retest == nil || baseline.Retest.FinishedAt == nil || baseline.Retest.FinishedAt.After(retest.CreatedAt) || !assessed {
			return nil, fmt.Errorf("%w: Can only be used based on previous runs that have ended and had their verdicts saved", ErrDefenseInvalid)
		}
	}
	var diagnosis json.RawMessage
	err = tx.QueryRowContext(ctx, `SELECT jsonb_build_object('finding',snapshot->'finding','constraints',COALESCE(snapshot->'constraints','[]'::jsonb),
	'assets',COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object('id',a->'id','type',a->'type','domain',a->'domain','ip',a->'ip','port',a->'port','url',a->'url','method',a->'method')) ORDER BY (a->>'id')::bigint)
	FROM jsonb_array_elements(COALESCE(NULLIF(snapshot->'assets','null'::jsonb),'[]'::jsonb)) a),'[]'::jsonb)) FROM finding_retests WHERE id=$1 AND finding_id=$2`, retest.ID, findingID).Scan(&diagnosis)
	if err != nil {
		return nil, err
	}
	copyRetest := *retest
	copyRetest.Snapshot = nil
	rawRetest, err := json.Marshal(&copyRetest)
	if err != nil {
		return nil, err
	}
	rawPlan, err := json.Marshal(state.Plan)
	if err != nil {
		return nil, err
	}
	var id int64
	err = tx.QueryRowContext(ctx, `INSERT INTO finding_defense_executions(finding_id,source_id,source_revision,source_snapshot,retest_id,retest_snapshot,diagnosis_snapshot,correlation_id,plan_snapshot,evidence_version,source_fingerprint,baseline_id,remediation_note,source_kind)
	 VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id`, findingID, in.SourceID, revision, source, retest.ID, rawRetest, diagnosis, uuid.NewString(), rawPlan, state.EvidenceVersion, state.SourceFingerprint, in.BaselineID, in.RemediationNote, in.SourceKind).Scan(&id)
	if err != nil {
		return nil, err
	}
	return getDefenseExecutionTx(ctx, tx, findingID, id)
}

// The first terminal snapshot is frozen. The trigger covers conversation
// deletion/recovery too, while this helper makes the transaction hook explicit.
func snapshotDefenseRetestTx(ctx context.Context, tx *sql.Tx, retestID int64) error {
	_, err := tx.ExecContext(ctx, `UPDATE finding_defense_executions e SET retest_snapshot=to_jsonb(r)-'snapshot' FROM finding_retests r
	WHERE e.retest_id=$1 AND r.id=e.retest_id AND COALESCE(e.retest_snapshot->>'status','') NOT IN ('completed','failed','stopped')`, retestID)
	return err
}

func (d *DB) GetDefenseExecution(ctx context.Context, findingID, id int64) (*DefenseExecution, error) {
	tx, err := d.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	e, err := getDefenseExecutionTx(ctx, tx, findingID, id)
	if err != nil {
		return nil, err
	}
	return e, tx.Commit()
}

// Collection preparation needs the frozen source and retest, not every prior
// uploaded file. Full raw history remains available only through the export read.
func (d *DB) GetDefenseExecutionForCollection(ctx context.Context, findingID, id int64) (*DefenseExecution, error) {
	tx, err := d.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	e, err := getDefenseExecutionMetadataTx(ctx, tx, findingID, id)
	if err != nil {
		return nil, err
	}
	return e, tx.Commit()
}

func (d *DB) ListDefenseExecutions(ctx context.Context, findingID int64) ([]*DefenseExecution, error) {
	tx, err := d.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	var exists bool
	if err := tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM findings WHERE id=$1)`, findingID).Scan(&exists); err != nil {
		return nil, err
	}
	if !exists {
		return nil, ErrFindingNotFound
	}
	rows, err := tx.QueryContext(ctx, executionSelect+`WHERE e.finding_id=$1 ORDER BY e.id DESC LIMIT 30`, findingID)
	if err != nil {
		return nil, err
	}
	out := []*DefenseExecution{}
	for rows.Next() {
		e, err := scanDefenseExecution(rows)
		if err != nil {
			rows.Close()
			return nil, err
		}
		out = append(out, e)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	for _, e := range out {
		e.DiagnosisSnapshot = nil
		if err := loadDefenseAssessmentsTx(ctx, tx, e, true); err != nil {
			return nil, err
		}
	}
	return out, tx.Commit()
}

func (d *DB) DefenseExecutionForRetest(ctx context.Context, retestID int64) (*DefenseExecution, error) {
	var findingID, id int64
	err := d.QueryRowContext(ctx, `SELECT finding_id,id FROM finding_defense_executions WHERE retest_id=$1`, retestID).Scan(&findingID, &id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return d.GetDefenseExecution(ctx, findingID, id)
}

func countDefenseEvidence(a *DefenseAssessment) {
	a.EventCount, a.AuditCount, a.AlertCount = 0, 0, 0
	if a.Evidence == nil {
		return
	}
	a.EventCount = len(a.Evidence.Events)
	for _, event := range a.Evidence.Events {
		switch event.Kind {
		case "audit":
			a.AuditCount++
		case "alert":
			a.AlertCount++
		}
	}
}

func previewDefenseAssessment(a *DefenseAssessment) *DefenseAssessment {
	if a.Evidence == nil {
		return a
	}
	copy := *a
	ev := *a.Evidence
	limit := len(ev.Events)
	if limit > 20 {
		limit = 20
	}
	ev.Events = append([]securitysource.Event{}, ev.Events[:limit]...)
	for i := range ev.Events {
		ev.Events[i].Raw = nil
	}
	copy.Evidence = &ev
	copy.EvidenceTruncated = len(a.Evidence.Events) > limit
	for _, event := range a.Evidence.Events {
		if len(event.Raw) > 0 {
			copy.EvidenceTruncated = true
			break
		}
	}
	if ev.Upload != nil {
		upload := *ev.Upload
		upload.Files = append([]securitysource.UploadedFileEvidence{}, ev.Upload.Files...)
		for i := range upload.Files {
			if upload.Files[i].Content != "" {
				copy.EvidenceTruncated = true
			}
			upload.Files[i].Content = ""
		}
		ev.Upload = &upload
	}
	return &copy
}

// assessDefenseEvidence does not read a model verdict or HTTP status. Only a
// completed test and correlated source artifacts can support its conclusions.
func assessDefenseEvidence(e *DefenseExecution, evidence *securitysource.Evidence) (*DefenseAssessment, error) {
	if e == nil || evidence == nil || evidence.CollectedAt.IsZero() || evidence.WindowStart.IsZero() || !evidence.WindowEnd.After(evidence.WindowStart) || evidence.WindowEnd.Sub(evidence.WindowStart) > 24*time.Hour || evidence.CollectedAt.Before(evidence.WindowEnd) || evidence.CollectedAt.After(time.Now().Add(5*time.Minute)) || len(evidence.Events) > 400 {
		return nil, fmt.Errorf("%w: Please check the evidence collection time, inquiry range, and number of events.", ErrDefenseInvalid)
	}
	if _, err := uuid.Parse(e.CorrelationID); err != nil {
		return nil, fmt.Errorf("%w: Execution correlation ID is incorrect", ErrDefenseInvalid)
	}
	raw, err := json.Marshal(evidence)
	if err != nil {
		return nil, fmt.Errorf("%w: Evidence format is incorrect", ErrDefenseInvalid)
	}
	maxBytes := 16 << 20
	if e.SourceKind == "file" {
		maxBytes = 32 << 20
	}
	if len(raw) > maxBytes || defenseJSONContainsNUL(raw) {
		return nil, fmt.Errorf("%w: Please check the size and characters of the evidence", ErrDefenseInvalid)
	}
	if err := validateDefenseEvidenceSource(e, evidence); err != nil {
		return nil, err
	}
	out := &DefenseAssessment{ExecutionID: e.ID, Detection: "inconclusive", Prevention: "inconclusive", Reasons: []string{}, Recommendations: []string{}, Diagnostics: append([]securitysource.Diagnostic{}, evidence.Diagnostics...), Evidence: evidence}
	reliable := true
	add := func(code, certainty, reason, recommendation string) {
		out.Reasons = append(out.Reasons, reason)
		out.Recommendations = append(out.Recommendations, recommendation)
		out.Diagnostics = append(out.Diagnostics, securitysource.Diagnostic{Code: code, Certainty: certainty, Message: reason, Recommendation: recommendation})
	}
	for _, diagnostic := range evidence.Diagnostics {
		out.Reasons = append(out.Reasons, diagnostic.Message)
		out.Recommendations = append(out.Recommendations, diagnostic.Recommendation)
	}
	if evidence.Upload != nil {
		add("file_coverage_attested", "observed", "File determination depends on the log source and search range confirmed by the uploader and is not an independently verified collection result.", "Check the query conditions and time range in the original log system and archive the exported files.")
		if !evidence.Upload.CoverageComplete {
			reliable = false
			add("file_coverage_unconfirmed", "observed", "There is no confirmation from the uploader that the entire range of views was included", "Make sure the audit/alert log covers the entire execution time range and upload it again.")
		}
		hasAudit, hasAlert := false, false
		for _, file := range evidence.Upload.Files {
			hasAudit = hasAudit || file.Kind == "audit"
			hasAlert = hasAlert || file.Kind == "alert"
		}
		if !hasAudit {
			reliable = false
			add("audit_file_missing", "observed", "Audit log file not provided", "Upload the original audit log with execution correlation ID and action fields")
		}
		if !hasAlert && !evidence.Upload.NoAlerts {
			reliable = false
			add("alert_export_unconfirmed", "observed", "No alert files or 0 alert confirmations were provided", "Upload an alert file with the same range or check that there are 0 alerts in the original query")
		}
	}
	if e.Retest == nil || e.Retest.Status != "completed" || e.Retest.FinishedAt == nil || e.Retest.Error != "" {
		reliable = false
		add("retest_incomplete", "observed", "Defense judgment is on hold because re-verification has not been completed properly.", "Check revalidation execution status and errors and re-collect evidence of successful execution")
	}
	if !evidence.Complete || len(evidence.Warnings) > 0 {
		reliable = false
		add("evidence_incomplete", "observed", "Log query is incomplete or has collection warnings", "Please check the log inquiry scope, export limit, and collector status and resubmit evidence of the same execution.")
	}
	if e.Retest != nil {
		start := e.Retest.CreatedAt
		if e.Retest.StartedAt != nil {
			start = *e.Retest.StartedAt
		}
		if start.IsZero() || evidence.WindowStart.After(start.Add(-30*time.Second)) || e.Retest.FinishedAt != nil && (e.Retest.FinishedAt.Before(start) || evidence.WindowEnd.Before(*e.Retest.FinishedAt)) {
			reliable = false
			add("window_incomplete", "observed", "The query scope does not completely cover the revalidation run section.", "Please check again, including the collection waiting period from 30 seconds before the start of execution to after completion.")
		}
	}
	audits, alerts, blocked, allowed, unknown := 0, 0, 0, 0, 0
	seen := map[string]bool{}
	inconsistent := false
	for _, event := range evidence.Events {
		key := event.Kind + ":" + event.ID
		if event.ID == "" || len(event.ID) > 1024 || event.Kind != "audit" && event.Kind != "alert" || event.CorrelationID != e.CorrelationID || event.OccurredAt.Before(evidence.WindowStart) || !event.OccurredAt.Before(evidence.WindowEnd) || seen[key] || event.Action != "blocked" && event.Action != "allowed" && event.Action != "unknown" {
			inconsistent = true
			continue
		}
		seen[key] = true
		if event.Kind == "alert" {
			alerts++
			continue
		}
		audits++
		switch event.Action {
		case "blocked":
			blocked++
		case "allowed":
			allowed++
		default:
			unknown++
		}
	}
	if inconsistent {
		reliable = false
		add("event_inconsistent", "observed", "Execution correlation ID/event time/identifier is inconsistent", "Check whether the same ARTEX execution UUID is recorded in the audit/alarm log and the time/duplicate collection settings.")
	}
	if audits == 0 {
		reliable = false
		add("audit_missing", "observed", "There are no audit logs associated with this run", "Check the forwarding of correlation headers in revalidation requests and the mapping of correlation fields to audit log export scope. The detection cannot be confirmed simply because there is no log.")
	}
	if !reliable {
		return out, nil
	}
	if alerts > 0 {
		out.Detection = "detected"
	} else {
		settled := e.Retest.FinishedAt.Add(60 * time.Second)
		if evidence.CollectedAt.Before(settled) || evidence.WindowEnd.Before(settled) {
			add("settling", "observed", "Alert collection latency of 60 seconds has not yet been met", "Collect logs again up to 60 seconds after the end of re-verification and check whether there are any false positives.")
		} else {
			out.Detection = "missed"
			add("alert_absent", "observed", "There are audit logs in the provided query scope, but no alarms are associated with the same execution.", "Recheck the original alarm query and export range with the same execution UUID")
			add("rule_gap", "hypothesis", "This may be due to missing rule condition/field mapping/activation or alert UUID delivery, but cannot be confirmed from this log alone.", "Check the detection rule conditions, activation status, and correlation ID passing of the alert, and compare them with a new run after making changes.")
		}
	}
	switch {
	case blocked > 0 && allowed == 0 && unknown == 0:
		out.Prevention = "blocked"
	case allowed > 0 && blocked == 0 && unknown == 0:
		out.Prevention = "not_blocked"
		add("audit_allowed", "observed", "Access permission actions were recorded in the audit log", "Review the authorization/blocking policy for the vulnerability and leave actual changes to verify with subsequent execution.")
	default:
		add("action_ambiguous", "observed", "Actions in audit logs are mixed or unspecified", "Map action fields to record actual blocked or allowed results and determine the cause of mixed results")
	}
	return out, nil
}

func validateDefenseEvidenceSource(e *DefenseExecution, evidence *securitysource.Evidence) error {
	if e.SourceKind != "file" {
		if evidence.Upload != nil {
			return fmt.Errorf("%w: Splunk execution cannot save file evidence", ErrDefenseInvalid)
		}
		return nil
	}
	config, err := defenseExecutionFileConfig(e)
	if err != nil {
		return err
	}
	if evidence.Upload == nil || evidence.Upload.Config != config {
		return fmt.Errorf("%w: Execution requires upload evidence matching fixed file origin/field mapping", ErrDefenseInvalid)
	}
	if len(evidence.Upload.Files) > 2 {
		return fmt.Errorf("%w: Only one audit and alarm file can be provided each.", ErrDefenseInvalid)
	}
	total := 0
	seen := map[string]bool{}
	for _, file := range evidence.Upload.Files {
		sum := sha256.Sum256([]byte(file.Content))
		if file.Kind != "audit" && file.Kind != "alert" || seen[file.Kind] || file.Name == "" || file.Bytes != len(file.Content) || file.Rows < 0 || file.SHA256 != fmt.Sprintf("%x", sum) {
			return fmt.Errorf("%w: The original, hash, and source information of the uploaded file do not match.", ErrDefenseInvalid)
		}
		seen[file.Kind] = true
		total += len(file.Content)
	}
	if evidence.Upload.NoAlerts && seen["alert"] {
		return fmt.Errorf("%w: Alert file and 0 alert confirmation cannot be submitted at the same time", ErrDefenseInvalid)
	}
	if evidence.Upload.NoAlerts {
		for _, event := range evidence.Events {
			if event.Kind == "alert" {
				return fmt.Errorf("%w: Confirmation of 0 alarms and actual alarm events are contradictory", ErrDefenseInvalid)
			}
		}
	}
	if total > securitysource.MaxUploadBytes {
		return fmt.Errorf("%w: Exceeded upload original size limit", ErrDefenseInvalid)
	}
	return nil
}

// PostgreSQL JSONB rejects actual NUL characters. A literal backslash-u0000 in
// an uploaded file is ordinary text and must not be confused with decoded NUL.
func defenseJSONContainsNUL(raw []byte) bool {
	if !bytes.Contains(raw, []byte(`\u0000`)) {
		return false
	}
	var value any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&value) != nil {
		return true
	}
	var contains func(any) bool
	contains = func(v any) bool {
		switch x := v.(type) {
		case string:
			return strings.ContainsRune(x, 0)
		case []any:
			for _, element := range x {
				if contains(element) {
					return true
				}
			}
		case map[string]any:
			for key, element := range x {
				if strings.ContainsRune(key, 0) || contains(element) {
					return true
				}
			}
		}
		return false
	}
	return contains(value)
}

func defenseExecutionFileConfig(e *DefenseExecution) (securitysource.FileConfig, error) {
	var snapshot struct {
		Kind     string                    `json:"kind"`
		Name     string                    `json:"name"`
		Revision int64                     `json:"revision"`
		Config   securitysource.FileConfig `json:"config"`
	}
	if json.Unmarshal(e.SourceSnapshot, &snapshot) != nil || snapshot.Kind != "file" || snapshot.Revision != 1 || e.SourceRevision != 1 || e.SourceID != 0 {
		return snapshot.Config, fmt.Errorf("%w: File origin snapshot is incorrect", ErrDefenseInvalid)
	}
	config, err := securitysource.ValidateFileConfig(snapshot.Config)
	if err != nil || config != snapshot.Config || snapshot.Name != config.Label {
		return config, fmt.Errorf("%w: File origin snapshot settings are incorrect", ErrDefenseInvalid)
	}
	return config, nil
}

func (d *DB) SaveDefenseAssessment(ctx context.Context, findingID, executionID int64, evidence *securitysource.Evidence) (*DefenseAssessment, error) {
	tx, err := d.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	if err := LockFindingEvidenceTx(tx, findingID, nil); err != nil {
		return nil, err
	}
	e, err := getDefenseExecutionMetadataTx(ctx, tx, findingID, executionID)
	if err != nil {
		return nil, err
	}
	if e.SourceKind == "splunk" {
		var enabled, configMatches bool
		var revision int64
		err = tx.QueryRowContext(ctx, `SELECT s.enabled,s.revision,s.config=e.source_snapshot->'config' FROM security_sources s JOIN finding_defense_executions e ON e.source_id=s.id WHERE s.id=$1 AND e.id=$2 FOR SHARE OF s`, e.SourceID, e.ID).Scan(&enabled, &revision, &configMatches)
		if errors.Is(err, sql.ErrNoRows) || err == nil && (!enabled || revision != e.SourceRevision || !configMatches) {
			return nil, ErrDefenseConflict
		}
		if err != nil {
			return nil, err
		}
	}
	a, err := assessDefenseEvidence(e, evidence)
	if err != nil {
		return nil, err
	}
	reasons, _ := json.Marshal(a.Reasons)
	recommendations, _ := json.Marshal(a.Recommendations)
	diagnostics, _ := json.Marshal(a.Diagnostics)
	raw, err := json.Marshal(evidence)
	if err != nil {
		return nil, err
	}
	out, err := scanDefenseAssessment(tx.QueryRowContext(ctx, `INSERT INTO finding_defense_assessments(finding_id,execution_id,detection,prevention,reasons,recommendations,diagnostics,evidence)
	VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id,execution_id,detection,prevention,reasons,recommendations,diagnostics,evidence,created_at`, findingID, executionID, a.Detection, a.Prevention, reasons, recommendations, diagnostics, raw))
	if err != nil {
		return nil, err
	}
	return out, tx.Commit()
}

func (d *DB) CompareDefenseExecutions(ctx context.Context, findingID, baselineID, currentID int64) (*DefenseComparison, error) {
	tx, err := d.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	baseline, err := getDefenseExecutionMetadataTx(ctx, tx, findingID, baselineID)
	if err != nil {
		return nil, err
	}
	current, err := getDefenseExecutionMetadataTx(ctx, tx, findingID, currentID)
	if err != nil {
		return nil, err
	}
	for _, execution := range []*DefenseExecution{baseline, current} {
		if err := loadDefenseAssessmentsTx(ctx, tx, execution, true); err != nil {
			return nil, err
		}
	}
	out := &DefenseComparison{Baseline: baseline, Current: current, Comparable: true, Reasons: []string{}}
	reject := func(reason string) { out.Comparable = false; out.Reasons = append(out.Reasons, reason) }
	if baselineID == currentID || current.BaselineID == nil || *current.BaselineID != baselineID {
		reject("Improvement practices are not explicitly linked to selected baseline practices")
	}
	if current.RemediationNote == "" {
		reject("No remedial action description")
	}
	baselineScope, baselineScopeOK := defenseDiagnosisScope(baseline.DiagnosisSnapshot)
	currentScope, currentScopeOK := defenseDiagnosisScope(current.DiagnosisSnapshot)
	if !baselineScopeOK || !currentScopeOK {
		reject("The original diagnostic scope snapshot is missing, so it is impossible to determine if it is the same")
	} else if baselineScope != currentScope {
		reject("The source target assets, vulnerability types, and task constraints of the two executions are different.")
	}

	if baseline.SourceKind != current.SourceKind {
		reject("The types of evidence sources for the two executions are different")
	} else if baseline.SourceKind == "file" {
		baselineConfig, baselineErr := defenseExecutionFileConfig(baseline)
		currentConfig, currentErr := defenseExecutionFileConfig(current)
		if baselineErr != nil || currentErr != nil || baselineConfig != currentConfig {
			reject("The two runs have different file log origin names or field mappings")
		}
	} else if baseline.SourceID != current.SourceID || baseline.SourceRevision != current.SourceRevision {
		reject("The evidence sources or settings versions of the two executions are different")
	}
	if current.State != "current" {
		reject("Plans, vulnerability evidence, target assets, task constraints, and source settings have changed since the current run.")
	}
	for _, e := range []*DefenseExecution{baseline, current} {
		if e.Retest == nil || e.Retest.Status != "completed" || e.Retest.FinishedAt == nil {
			reject("Both revalidations must complete successfully")
			break
		}
	}
	if len(baseline.Assessments) == 0 || len(current.Assessments) == 0 {
		reject("Both runs require a saved source verdict")
	} else {
		for _, a := range []*DefenseAssessment{baseline.Assessments[0], current.Assessments[0]} {
			if a.Detection == "inconclusive" || a.Prevention == "inconclusive" {
				reject("Improvements cannot be confirmed due to uncertain detection and blocking results in the latest judgment.")
				break
			}
		}
	}
	if baseline.Retest != nil && baseline.Retest.FinishedAt != nil && current.Retest != nil && baseline.Retest.FinishedAt.After(current.Retest.CreatedAt) {
		reject("The baseline run did not end before the improvement run")
	}
	// Correlation UUIDs are intentionally different per run. Comparability is
	// established by the same source configuration, not equality of raw IDs.
	if _, err := uuid.Parse(baseline.CorrelationID); err != nil {
		reject("Base run correlation ID is incorrect")
	}
	if _, err := uuid.Parse(current.CorrelationID); err != nil {
		reject("Remediation run correlation ID is incorrect")
	}
	return out, tx.Commit()
}

// Marshal only the diagnostic target/constraints for comparison. Rules, evidence
// content and remediation may evolve, but a different target is not a baseline.
func defenseDiagnosisScope(raw json.RawMessage) (string, bool) {
	type constraint struct {
		Kind string `json:"kind"`
		Text string `json:"text"`
	}
	var snapshot struct {
		Finding     json.RawMessage              `json:"finding"`
		Assets      []map[string]json.RawMessage `json:"assets"`
		Constraints []constraint                 `json:"constraints"`
	}
	if json.Unmarshal(raw, &snapshot) != nil || len(snapshot.Finding) == 0 || string(snapshot.Finding) == "null" || snapshot.Assets == nil || snapshot.Constraints == nil {
		return "", false
	}
	var finding struct {
		VulnClass string `json:"vulnclass"`
	}
	if json.Unmarshal(snapshot.Finding, &finding) != nil {
		return "", false
	}
	assetIDs := make(map[string]int64, len(snapshot.Assets))
	for i, asset := range snapshot.Assets {
		var id int64
		if json.Unmarshal(asset["id"], &id) != nil || id <= 0 {
			return "", false
		}
		filtered := make(map[string]json.RawMessage)
		for _, key := range []string{"id", "type", "domain", "ip", "port", "url", "method"} {
			if value := asset[key]; len(value) > 0 && string(value) != "null" {
				filtered[key] = value
			}
		}
		snapshot.Assets[i] = filtered
		assetIDs[string(filtered["id"])] = id
	}
	sort.Slice(snapshot.Assets, func(i, j int) bool {
		return assetIDs[string(snapshot.Assets[i]["id"])] < assetIDs[string(snapshot.Assets[j]["id"])]
	})
	sort.Slice(snapshot.Constraints, func(i, j int) bool {
		if snapshot.Constraints[i].Kind != snapshot.Constraints[j].Kind {
			return snapshot.Constraints[i].Kind < snapshot.Constraints[j].Kind
		}
		return snapshot.Constraints[i].Text < snapshot.Constraints[j].Text
	})
	value := struct {
		VulnClass   string
		Assets      []map[string]json.RawMessage
		Constraints []constraint
	}{finding.VulnClass, snapshot.Assets, snapshot.Constraints}
	b, err := json.Marshal(value)
	return string(b), err == nil
}
