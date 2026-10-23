package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/Autumn-27/norma/transcript"
	"github.com/desanv01/omniforge/agent"
	"github.com/desanv01/omniforge/db"
	"github.com/desanv01/omniforge/investigation"
	"github.com/desanv01/omniforge/securitysource"
)

func (s *Server) registerDefensiveCaseRuns(mux *http.ServeMux) {
	const route = "/api/defensive/cases/{id}/runs"
	mux.HandleFunc("GET "+route, s.listDefensiveCaseRuns)
	mux.HandleFunc("POST "+route, s.startDefensiveCaseRun)
	mux.HandleFunc("GET "+route+"/{runID}", s.getDefensiveCaseRun)
	mux.HandleFunc("GET "+route+"/{runID}/export", s.exportDefensiveCaseRun)
	mux.HandleFunc("POST "+route+"/{runID}/cancel", s.cancelDefensiveCaseRun)
}

func (s *Server) defensiveCaseRunBase(w http.ResponseWriter, r *http.Request) (*db.DefensiveCase, bool) {
	return s.readDefensiveCase(w, r)
}

func (s *Server) listDefensiveCaseRuns(w http.ResponseWriter, r *http.Request) {
	base, ok := s.defensiveCaseRunBase(w, r)
	if !ok {
		return
	}
	runs, err := s.m.pg.ListDefensiveCaseRuns(r.Context(), base.ID)
	if err != nil {
		defensiveCaseError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{"runs": runs})
}

func (s *Server) readDefensiveCaseRun(w http.ResponseWriter, r *http.Request) (*db.DefensiveCase, *db.DefensiveCaseRun, bool) {
	base, ok := s.defensiveCaseRunBase(w, r)
	if !ok {
		return nil, nil, false
	}
	id, ok := pathInt(r, "runID")
	if !ok || id <= 0 {
		writeErr(w, 400, "Please check your survey run ID")
		return nil, nil, false
	}
	run, err := s.m.pg.GetDefensiveCaseRun(r.Context(), base.ID, id)
	if err == nil && run.CaseID != base.ID {
		err = db.ErrDefensiveCaseRunNotFound
	}
	if err != nil {
		defensiveCaseError(w, err)
		return nil, nil, false
	}
	return base, run, true
}

// Ordinary polling returns selected evidence, never whole uploaded files.
func defensiveCaseRunPreview(run *db.DefensiveCaseRun) *db.DefensiveCaseRun {
	out := *run
	out.Events = append([]db.DefensiveCaseRunEvent{}, run.Events...)
	for i := range out.Events {
		if out.Events[i].Kind != "evidence_collection" {
			continue
		}
		var proof investigationQueryProof
		if json.Unmarshal(out.Events[i].Payload, &proof) != nil {
			continue
		}
		for j := range proof.Collection.Files {
			proof.Collection.Files[j].Content = ""
		}
		out.Events[i].Payload, _ = json.Marshal(proof)
	}
	return &out
}

func (s *Server) getDefensiveCaseRun(w http.ResponseWriter, r *http.Request) {
	_, run, ok := s.readDefensiveCaseRun(w, r)
	if !ok {
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, defensiveCaseRunPreview(run))
}

func (s *Server) exportDefensiveCaseRun(w http.ResponseWriter, r *http.Request) {
	base, run, ok := s.readDefensiveCaseRun(w, r)
	if !ok {
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="defensive-case-%d-agent-%d.json"`, base.ID, run.ID))
	writeJSON(w, 200, map[string]any{"case": base, "run": run})
}

func (s *Server) cancelDefensiveCaseRun(w http.ResponseWriter, r *http.Request) {
	base, run, ok := s.readDefensiveCaseRun(w, r)
	if !ok {
		return
	}
	s.investigationMu.Lock()
	run, err := s.m.pg.CancelDefensiveCaseRun(r.Context(), base.ID, run.ID)
	// Seal the durable state before waking the worker. Otherwise its cancelled
	// progress write can fail and race to seal this run as interrupted instead.
	if err == nil {
		if cancel := s.investigationCancel[-run.ID]; cancel != nil {
			cancel()
		}
	}
	s.investigationMu.Unlock()
	if err != nil {
		defensiveCaseError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, defensiveCaseRunPreview(run))
}

func (s *Server) startDefensiveCaseRun(w http.ResponseWriter, r *http.Request) {
	base, ok := s.defensiveCaseRunBase(w, r)
	if !ok {
		return
	}
	var in struct {
		Question string `json:"question"`
	}
	if !decodePurpleRequestLimit(w, r, &in, 32<<10) {
		return
	}
	in.Question = strings.TrimSpace(in.Question)
	if utf8.RuneCountInString(in.Question) > 4000 || strings.ContainsRune(in.Question, 0) {
		writeErr(w, 400, "Please enter survey questions within 4000 characters without NUL characters.")
		return
	}
	if in.Question == "" {
		in.Question = base.Question
	}
	if base.State != "current" {
		defensiveCaseError(w, db.ErrDefenseConflict)
		return
	}
	s.cfgMu.Lock()
	provider, cfg, profile := s.llmProv, s.llmCfg, s.llmProf
	ready := s.llmOn && provider != nil
	s.cfgMu.Unlock()
	if !ready {
		writeErr(w, 503, "AI Research requires an active LLM connection. Please check system → LLM settings")
		return
	}
	parent := s.ctx
	if parent == nil {
		parent = context.Background()
	}
	if parent.Err() != nil {
		writeErr(w, 503, "Service is ending")
		return
	}
	// Resolve query scope before creating a paid model run. Credentials never
	// enter the model options, prompt, result, or exported source snapshot.
	var source *db.SecuritySource
	var sourcetypes []string
	if base.SourceKind == "splunk" {
		var err error
		source, sourcetypes, err = s.defensiveCaseRunSource(r.Context(), base)
		if err != nil {
			defensiveCaseError(w, err)
			return
		}
	}
	options, _ := json.Marshal(map[string]any{"question": in.Question, "model": cfg.Model, "profile": profile, "source_kind": base.SourceKind, "remote_enabled": source != nil, "budget": map[string]int{"max_rounds": 3, "max_model_calls": 18, "max_queries": 12, "max_remote_queries": 3, "max_tokens": 180000, "timeout_seconds": 240}})
	s.investigationMu.Lock()
	if s.investigationCancel == nil {
		s.investigationCancel = map[int64]context.CancelFunc{}
	}
	if len(s.investigationCancel) > 0 {
		// Repeated clicks on the same active run are idempotent.
		for activeID := range s.investigationCancel {
			if activeID >= 0 {
				continue
			}
			if active, err := s.m.pg.GetDefensiveCaseRun(r.Context(), base.ID, -activeID); err == nil && active.CaseID == base.ID && (active.Status == "running" || active.Status == "queued") {
				s.investigationMu.Unlock()
				writeJSON(w, 202, defensiveCaseRunPreview(active))
				return
			}
		}
		s.investigationMu.Unlock()
		writeErr(w, 409, "Other AI investigations are underway. Please complete or stop before starting")
		return
	}
	run, created, err := s.m.pg.CreateDefensiveCaseRun(r.Context(), base.ID, options)
	if err != nil {
		s.investigationMu.Unlock()
		defensiveCaseError(w, err)
		return
	}
	if created {
		// Include persistence waits in the same deadline as model and log work.
		ctx, cancel := context.WithTimeout(parent, 4*time.Minute)
		s.investigationCancel[-run.ID] = cancel
		var transcripts *transcript.Store
		if s.m.dir != "" {
			transcripts = transcript.NewStore(filepath.Join(s.m.dir, "transcripts"))
		}
		opts := agent.InvestigatorOptions{Provider: provider, NonStreaming: !cfg.Stream, MaxTokens: cfg.MaxTokens, Transcript: transcripts, SessionID: fmt.Sprintf("defensive-case-%d", run.ID), Title: base.Title, Question: in.Question, Collection: base.Collection}
		if base.FindingSnapshot != nil {
			opts.Finding = *base.FindingSnapshot
		}

		go s.executeDefensiveCaseRun(ctx, cancel, run, base, source, sourcetypes, opts)
	}
	s.investigationMu.Unlock()
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 202, defensiveCaseRunPreview(run))
}

func (s *Server) defensiveCaseRunSource(ctx context.Context, base *db.DefensiveCase) (*db.SecuritySource, []string, error) {
	source, err := s.m.pg.GetSecuritySource(ctx, base.SourceID)
	if err != nil {
		return nil, nil, err
	}
	if !source.Enabled || !source.CredentialSet || source.Revision != base.SourceRevision {
		return nil, nil, db.ErrDefenseConflict
	}
	var snapshot struct {
		InvestigationSourcetypes []string `json:"investigation_sourcetypes"`
	}
	if err = json.Unmarshal(base.SourceSnapshot, &snapshot); err != nil {
		return nil, nil, err
	}
	query, err := securitysource.BuildInvestigationSearch(source.Config, base.Scope, base.Mapping, snapshot.InvestigationSourcetypes)
	if err != nil {
		return nil, nil, err
	}
	// Old default-source records are compatible. Old custom selections need a
	// new evidence collection because their authorization isn't separately stored.
	if query != base.Collection.Query {
		return nil, nil, fmt.Errorf("%w: The saved query range has changed. Please collect Splunk evidence again", db.ErrDefenseInvalid)
	}
	return source, snapshot.InvestigationSourcetypes, nil
}

func (s *Server) executeDefensiveCaseRun(ctx context.Context, cancel context.CancelFunc, run *db.DefensiveCaseRun, base *db.DefensiveCase, source *db.SecuritySource, sourcetypes []string, opts agent.InvestigatorOptions) {
	defer cancel()
	defer func() { s.investigationMu.Lock(); delete(s.investigationCancel, -run.ID); s.investigationMu.Unlock() }()
	started, err := s.m.pg.StartDefensiveCaseRun(ctx, run.ID)
	if err != nil {
		finishCtx, done := context.WithTimeout(context.Background(), 10*time.Second)
		_, finishErr := s.m.pg.FinishDefensiveCaseRun(finishCtx, run.ID, "interrupted", json.RawMessage(`{}`), "Failed to start investigation run. Please run again", db.InvestigationRunUsage{})
		done()
		if finishErr != nil {
			log.Printf("[defensive-case] run %d start cleanup failed: %v", run.ID, finishErr)
		}
		return
	}
	if !started {
		return
	}
	var mu sync.Mutex
	var usage db.InvestigationRunUsage
	var persistErr error
	storedBytes, remoteCalls := 0, 0
	appendEvent := func(kind string, payload any) error {
		raw, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		if storedBytes+len(raw) > 20<<20 {
			return fmt.Errorf("Investigation evidence retention limit has been reached")
		}
		_, err = s.m.pg.AppendDefensiveCaseRunEvent(ctx, run.ID, kind, raw, usage)
		if err == nil {
			storedBytes += len(raw)
		}
		return err
	}
	opts.Emit = func(progress agent.InvestigatorProgress) {
		if progress.Kind == "thinking" {
			return
		}
		mu.Lock()
		defer mu.Unlock()
		if persistErr != nil {
			return
		}
		usage.Rounds = max(usage.Rounds, int64(progress.Round))
		usage.ModelCalls = max(usage.ModelCalls, int64(progress.Usage.ModelCalls))
		usage.Queries = max(usage.Queries, int64(progress.Usage.Queries))
		usage.InputTokens = max(usage.InputTokens, int64(progress.Usage.InputTokens))
		usage.OutputTokens = max(usage.OutputTokens, int64(progress.Usage.OutputTokens))
		if progress.Kind == "tool_use" {
			usage.ToolCalls++
		}
		if err := appendEvent(progress.Kind, progress); err != nil {
			persistErr = err
			cancel()
		}
	}
	if source != nil {
		opts.Search = func(queryCtx context.Context, query agent.InvestigationSearch) (investigation.Collection, error) {
			var empty investigation.Collection
			if err := queryCtx.Err(); err != nil {
				return empty, err
			}
			active, err := s.m.pg.GetDefensiveCaseRun(queryCtx, base.ID, run.ID)
			if err != nil {
				return empty, err
			}
			if active.Status != "running" {
				return empty, db.ErrDefensiveCaseRunInactive
			}
			if err := validateInvestigationPivot(base.Scope, query); err != nil {
				return empty, err
			}
			mu.Lock()
			if persistErr != nil || remoteCalls >= 3 {
				mu.Unlock()
				return empty, fmt.Errorf("Splunk follow-up query limit reached")
			}
			remoteCalls++
			mu.Unlock()
			// Re-read revision immediately before each request; revoked/changed
			// credentials or source scope stop later pivots.
			current, _, err := s.defensiveCaseRunSource(queryCtx, base)
			if err != nil {
				return empty, err
			}
			auth, err := s.securitySourceCredentials(current)
			if err != nil {
				return empty, err
			}
			runs, err := s.m.pg.KnownDefensiveVerifications(queryCtx, base.Scope)
			if err != nil {
				return empty, err
			}
			ids := []string{}
			for _, known := range runs {
				ids = append(ids, known.ID)
			}
			collection, err := securitysource.FetchInvestigationFiltered(queryCtx, current.Config, auth, query.Scope, base.Mapping, sourcetypes, ids, securitysource.InvestigationFilters{SourceIP: query.SourceIP, User: query.User, Session: query.Session, EventKind: query.EventKind, PathContains: query.PathContains})
			if err != nil {
				return empty, err
			}
			boundDefensiveCaseMarkers(&collection, runs)
			mu.Lock()
			defer mu.Unlock()
			if err := appendEvent("evidence_collection", investigationQueryProof{query, collection}); err != nil {
				persistErr = err
				cancel()
				return empty, err
			}
			return collection, nil
		}
	}
	report, runErr := agent.RunInvestigation(ctx, opts)
	mu.Lock()
	usage.ModelCalls = max(usage.ModelCalls, int64(report.Usage.ModelCalls))
	usage.Queries = max(usage.Queries, int64(report.Usage.Queries))
	usage.InputTokens = max(usage.InputTokens, int64(report.Usage.InputTokens))
	usage.OutputTokens = max(usage.OutputTokens, int64(report.Usage.OutputTokens))
	// Progress and evidence are already persisted once in ordered events.
	report.Trace = nil
	report.Collections = nil
	message := ""
	if persistErr != nil && !errors.Is(persistErr, db.ErrDefensiveCaseRunInactive) {
		report.Status = "interrupted"
		message = "Failed to save investigation process, aborting further queries and model calls"
	} else if runErr != nil && report.Status == "model_error" {
		message = "The LLM call could not be completed. Please check your saved progress and LLM connections/limits."
	}
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		report.Status = "budget_exhausted"
		message = "The investigation time limit has been reached. Check the previously saved progress and evidence"
	}
	if s.ctx != nil && s.ctx.Err() != nil {
		report.Status = "interrupted"
		message = "The investigation was halted due to the termination of service. Check the saved rationale and start a new run"
	}
	raw, err := json.Marshal(report)
	if err != nil {
		raw = json.RawMessage(`{}`)
		report.Status = "interrupted"
		message = "Failed to serialize findings"
	}
	finishCtx, done := context.WithTimeout(context.Background(), 10*time.Second)
	_, err = s.m.pg.FinishDefensiveCaseRun(finishCtx, run.ID, report.Status, raw, message, usage)
	if err != nil { // Preserve a terminal state even when the final report is too large.
		_, err = s.m.pg.FinishDefensiveCaseRun(finishCtx, run.ID, "interrupted", json.RawMessage("{\"summary\":\"You have reached your results storage limit. Please see the research process and rationale preserved.\"}"), "Final result storage limit", usage)
	}
	done()
	mu.Unlock()
	if err != nil {
		log.Printf("[defensive-case] run %d finish failed: %v", run.ID, err)
	}
}
