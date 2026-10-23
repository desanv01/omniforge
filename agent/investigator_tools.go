package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	actool "github.com/Autumn-27/norma/tool"
	"github.com/desanv01/omniforge/investigation"
)

type investigatorPlanInput struct {
	Action       string   `json:"action"`
	Reason       string   `json:"reason"`
	Hypothesis   string   `json:"hypothesis"`
	Objective    string   `json:"objective"`
	EvidenceRefs []string `json:"evidence_refs"`
	NeededLogs   []string `json:"needed_logs"`
	NextSteps    []string `json:"next_steps"`
}

func certDecode(in json.RawMessage, out any) error {
	if len(in) > 16000 {
		return investigation.ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(in))
	d.DisallowUnknownFields()
	if err := d.Decode(out); err != nil {
		return err
	}
	if d.Decode(new(any)) != io.EOF {
		return investigation.ErrInvalid
	}
	return nil
}
func certArray(desc string) map[string]any {
	return map[string]any{"type": "array", "description": desc, "items": map[string]any{"type": "string"}}
}
func certObject(props map[string]any, required ...string) map[string]any {
	return map[string]any{"type": "object", "properties": props, "required": required, "additionalProperties": false}
}
func (r *investigatorRun) validateRefs(refs []string, require bool) error {
	if (require && len(refs) == 0) || len(refs) > 10 {
		return fmt.Errorf("Requires 1-10 real-world refs")
	}
	for _, ref := range refs {
		if !r.seen[ref] {
			return fmt.Errorf("This is a reference ref that I did not read in this run")
		}
	}
	return nil
}

func (r *investigatorRun) planTool() actool.CoreTool {
	return writeTool("plan_investigation", "Decide on your investigation hypothesis and next action, or stop due to lack of evidence or completion of investigation. Re-plan when the rationale changes and don't repeat existing work.", certObject(map[string]any{
		"action": map[string]any{"type": "string", "enum": []string{"investigate", "complete", "insufficient_data"}}, "reason": str("Reasons for making this decision based on current evidence"), "hypothesis": str("Conditional hypothesis not yet confirmed"), "objective": str("Specific actions that workers can check in logs"), "evidence_refs": certArray("Already verified original evidence ref; Leave empty in the initial plan"), "needed_logs": certArray("Insufficient logs and required fields"), "next_steps": certArray("Remaining investigation and detection improvement suggestions"),
	}, "action", "reason"), func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
		if err := ctx.Err(); err != nil {
			return actool.Errorf("Investigation is closed"), nil
		}
		var a investigatorPlanInput
		if err := certDecode(in, &a); err != nil {
			return actool.Errorf("Plan input format is incorrect"), nil
		}
		r.mu.Lock()
		defer r.mu.Unlock()
		if r.decision != nil {
			return actool.Errorf("The plan for this round has already been submitted. Please submit your new plan in the next round."), nil
		}
		if a.Action != "investigate" && a.Action != "complete" && a.Action != "insufficient_data" {
			return actool.Errorf("The plan status is not supported"), nil
		}
		if strings.TrimSpace(a.Reason) == "" || len(a.Reason) > 1600 || len(a.Hypothesis) > 1200 || len(a.Objective) > 1200 || certStrings(a.NeededLogs, 8, 500) != nil || certStrings(a.NextSteps, 8, 500) != nil {
			return actool.Errorf("Plan contents are empty or limit exceeded"), nil
		}
		if err := r.validateRefs(a.EvidenceRefs, false); err != nil {
			return actool.Errorf(err.Error()), nil
		}
		if a.Action == "investigate" {
			if strings.TrimSpace(a.Hypothesis) == "" || strings.TrimSpace(a.Objective) == "" {
				return actool.Errorf("Requires hypothesis and specific research work"), nil
			}
			for _, intent := range r.report.Intents {
				if strings.EqualFold(strings.TrimSpace(intent.Objective), strings.TrimSpace(a.Objective)) {
					return actool.Errorf("This operation has already been performed. Follow new evidence or leave necessary logs and stop"), nil
				}
			}
		}
		if a.Action == "complete" && (len(r.report.Intents) == 0 || len(r.report.Observations) == 0) {
			return actool.Errorf("This cannot be completed until the logs have been examined. Research or stop due to lack of data"), nil
		}
		r.decision = &a
		d := InvestigatorDecision{Round: r.round, Action: a.Action, Reason: a.Reason, EvidenceRefs: a.EvidenceRefs}
		r.report.Decisions = append(r.report.Decisions, d)
		r.report.Gaps = certUniqueStrings(append(r.report.Gaps, a.NeededLogs...))
		r.report.NextSteps = certUniqueStrings(append(r.report.NextSteps, a.NextSteps...))
		r.emitLocked(InvestigatorProgress{Kind: "decision", Summary: a.Reason, Decision: &d, EvidenceRefs: a.EvidenceRefs})
		return jsonResult(map[string]any{"saved": true, "action": a.Action, "instruction": "The plan for this episode has been saved. Simply quit. The host runs the worker."})
	})
}

// ValidateInvestigationSearch is shared with callers for defense in depth. No
// wildcard target, widened time window, or escape from the original path is
// possible through the typed query tool.
func ValidateInvestigationSearch(base investigation.Scope, q InvestigationSearch) error {
	if err := investigation.ValidateScope(q.Scope, time.Now()); err != nil {
		return err
	}
	if !strings.EqualFold(q.Scope.Target, base.Target) || q.Scope.Start.Before(base.Start) || q.Scope.End.After(base.End) || !q.Scope.Start.Before(q.Scope.End) {
		return fmt.Errorf("Hits cannot go beyond the initial target and time range")
	}
	if base.PathPrefix != "" && (q.Scope.PathPrefix == "" || !investigation.MatchPath(q.Scope.PathPrefix, base.PathPrefix)) {
		return fmt.Errorf("The query path must be within the range of the original path")
	}
	if q.Offset < 0 || q.Offset > investigation.MaxEvents || q.Remote && q.Offset != 0 {
		return investigation.ErrInvalid
	}
	for _, s := range []string{q.SourceIP, q.User, q.Session, q.EventKind, q.PathContains} {
		if len(s) > 256 || !utf8.ValidString(s) || strings.ContainsAny(s, "\r\n\x00") {
			return investigation.ErrInvalid
		}
	}
	return nil
}

func (r *investigatorRun) searchTool() actool.CoreTool {
	scopeSchema := certObject(map[string]any{"target": str("Maintain initial target"), "path_prefix": str("Path prefix within the initial range"), "start": str("RFC3339; After initial startup"), "end": str("RFC3339; Before initial termination")})
	return readTool("search_evidence", "Search logs using structured conditions. The default is to search in collected files/logs. Read-only addition query to connected Splunk only when remote=true. Check the 20 results each and the original text with read_evidence. Instead of repeating the same condition, request the next page with an offset.", certObject(map[string]any{
		"scope": scopeSchema, "source_ip": str("Source IP matching exactly"), "user": str("exact match account"), "session": str("exact match session"), "event_kind": str("Exact match event type"), "path_contains": str("Literal string to be included in the path"), "remote": map[string]any{"type": "boolean"}, "offset": map[string]any{"type": "integer", "minimum": 0},
	}), func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
		var q InvestigationSearch
		if err := certDecode(in, &q); err != nil {
			return actool.Errorf("The query input format is incorrect"), nil
		}
		base := r.report.Scope
		if q.Scope.Target == "" {
			q.Scope.Target = base.Target
		}
		if q.Scope.Start.IsZero() {
			q.Scope.Start = base.Start
		}
		if q.Scope.End.IsZero() {
			q.Scope.End = base.End
		}
		if q.Scope.PathPrefix == "" {
			q.Scope.PathPrefix = base.PathPrefix
		}
		if err := ValidateInvestigationSearch(base, q); err != nil {
			return actool.Errorf(err.Error()), nil
		}
		if err := ctx.Err(); err != nil {
			return actool.Errorf("Investigation is closed"), nil
		}
		r.mu.Lock()
		if r.emptyCompleteScope && len(r.events) == 0 {
			r.mu.Unlock()
			return actool.Errorf("No events were collected across the entire scope of the investigation. Rather than repeating changes by changing filters, record data shortages and check mapping/collection status with record_observation."), nil
		}
		// Event kinds are normalized values, not guessed product/sourcetype
		// names. Do not disguise a misspelled kind as a meaningful zero result.
		if !q.Remote && q.EventKind != "" && len(r.events) > 0 {
			kinds := map[string]int{}
			for _, e := range r.events {
				if e.EventKind != "" {
					kinds[e.EventKind]++
				}
			}
			if len(kinds) > 0 && kinds[q.EventKind] == 0 {
				available, _ := json.Marshal(certCounts(kinds))
				r.mu.Unlock()
				return actool.Errorf(fmt.Sprintf("This event_kind value does not exist in the saved log. The actual type is %s. Remove type filter or use actual value", string(available))), nil
			}
		}
		page := q
		page.Offset = 0
		pageKey, _ := json.Marshal(page)
		if total, ok := r.queryTotals[string(pageKey)]; ok && q.Offset >= total {
			r.mu.Unlock()
			return actool.Errorf("There is no next page for this query. Record the evidence obtained or leave necessary logs"), nil
		}
		key, _ := json.Marshal(q)
		if r.queryKeys[string(key)] {
			r.mu.Unlock()
			return actool.Errorf("You have already performed the same query. Check the existing evidence or the next page"), nil
		}
		if q.Remote && (r.opts.Search == nil || r.remoteQueries >= 3) {
			r.mu.Unlock()
			return actool.Errorf("Splunk additional hits are not available or the limit of 3 has been exhausted. Record the logs you need"), nil
		}
		if err := r.provider.query(); err != nil {
			r.mu.Unlock()
			return actool.Errorf(err.Error()), nil
		}
		r.queryKeys[string(key)] = true
		r.report.Searches = append(r.report.Searches, q)
		if q.Remote {
			r.remoteQueries++
		}
		r.mu.Unlock()
		var selected []investigation.Event
		if q.Remote {
			c, err := r.opts.Search(ctx, q)
			if err != nil {
				return actool.Errorf("Splunk query failed. Check connection status, log fields, and allowable range."), nil
			}
			body, err := json.Marshal(c)
			r.mu.Lock()
			defer r.mu.Unlock()
			if err != nil || len(c.Events) > investigation.MaxEvents || len(body)+r.evidenceBytes > 24<<20 {
				return actool.Errorf("The additional evidence storage limit has been exceeded. A narrower scope is needed"), nil
			}
			if err := ValidateInvestigationSearch(q.Scope, InvestigationSearch{Scope: c.Scope}); err != nil {
				return actool.Errorf("The query response was outside the scope of the request"), nil
			}
			for _, e := range c.Events {
				if e.Ref == "" || !r.inScope(e, q.Scope) {
					continue
				}
				if old, ok := r.events[e.Ref]; ok && (old.Raw != e.Raw || old.FileName != e.FileName || old.Line != e.Line) {
					return actool.Errorf("The basis identifier for the additional evidence conflicts with existing evidence"), nil
				}
			}
			r.report.Collections = append(r.report.Collections, c)
			r.evidenceBytes += len(body)
			r.report.Gaps = certUniqueStrings(append(r.report.Gaps, c.Warnings...))
			if !c.Complete {
				r.report.Gaps = certUniqueStrings(append(r.report.Gaps, "Additional Splunk query results contain collection scope or truncation warnings."))
			}
			for _, e := range c.Events {
				if e.Ref != "" && r.inScope(e, q.Scope) {
					r.events[e.Ref] = e
					if certMatch(e, q) {
						selected = append(selected, e)
					}
				}
			}
			if c.Complete && len(r.events) == 0 && q.Scope.Target == base.Target && q.Scope.Start.Equal(base.Start) && q.Scope.End.Equal(base.End) && q.Scope.PathPrefix == base.PathPrefix && q.SourceIP == "" && q.User == "" && q.Session == "" && q.EventKind == "" && q.PathContains == "" {
				r.emptyCompleteScope = true
			}
			return r.searchResultLocked(q, selected)
		}
		r.mu.Lock()
		defer r.mu.Unlock()
		for _, e := range r.events {
			if r.inScope(e, q.Scope) && certMatch(e, q) {
				selected = append(selected, e)
			}
		}
		return r.searchResultLocked(q, selected)
	})
}

func certMatch(e investigation.Event, q InvestigationSearch) bool {
	return (q.SourceIP == "" || e.SourceIP == q.SourceIP) && (q.User == "" || e.User == q.User) && (q.Session == "" || e.Session == q.Session) && (q.EventKind == "" || e.EventKind == q.EventKind) && (q.PathContains == "" || strings.Contains(e.Path, q.PathContains))
}
func (r *investigatorRun) searchResultLocked(q InvestigationSearch, selected []investigation.Event) (actool.Result, error) {
	sort.Slice(selected, func(i, j int) bool {
		if selected[i].Timestamp.Equal(selected[j].Timestamp) {
			return selected[i].Ref < selected[j].Ref
		}
		return selected[i].Timestamp.Before(selected[j].Timestamp)
	})
	total := len(selected)
	page := q
	page.Offset = 0
	key, _ := json.Marshal(page)
	if r.queryTotals == nil {
		r.queryTotals = map[string]int{}
	}
	r.queryTotals[string(key)] = total
	start := min(q.Offset, total)
	end := min(start+20, total)
	rows := make([]investigation.Event, 0, end-start)
	refs := make([]string, 0, end-start)
	for _, e := range selected[start:end] {
		r.seen[e.Ref] = true
		refs = append(refs, e.Ref)
		e.Raw = ""
		e.Path = certClip(e.Path, 400)
		e.User = certClip(e.User, 160)
		e.Session = certClip(e.Session, 160)
		e.Action = certClip(e.Action, 160)
		rows = append(rows, e)
	}
	r.emitLocked(InvestigatorProgress{Kind: "query", Summary: fmt.Sprintf("As a result of the search, %[2]d out of %[1]d was confirmed.", total, len(rows)), EvidenceRefs: refs})
	return jsonResult(map[string]any{"events": rows, "total_matches": total, "next_offset": end, "has_more": end < total, "scope": q.Scope, "all_scope_empty": r.emptyCompleteScope, "instruction": "Once you have the results, check the original text and save it as record_observation first. If there are 0 cases and has_more=false, do not repeat by changing the offset.", "warning": "This is part of the evidence viewed. No observation does not mean no infringement. Check raw with read_evidence."})
}

func (r *investigatorRun) readTool() actool.CoreTool {
	return readTool("read_evidence", "View up to 5 original sources of evidence. ref must be the actual identifier provided in search_evidence. If the original text is long, only up to 4096 bytes are displayed, and the entire original text is preserved in local evidence.", certObject(map[string]any{"refs": certArray("List of refs to check")}, "refs"), func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
		if ctx.Err() != nil {
			return actool.Errorf("Investigation is closed"), nil
		}
		var a struct {
			Refs []string `json:"refs"`
		}
		if certDecode(in, &a) != nil || len(a.Refs) == 0 || len(a.Refs) > 5 {
			return actool.Errorf("Requires 1-5 refs"), nil
		}
		r.mu.Lock()
		defer r.mu.Unlock()
		if err := r.validateRefs(a.Refs, true); err != nil {
			return actool.Errorf(err.Error()), nil
		}
		rows := make([]map[string]any, 0, len(a.Refs))
		for _, ref := range a.Refs {
			e := r.events[ref]
			r.rawSeen[ref] = true
			rows = append(rows, map[string]any{"ref": ref, "file_name": e.FileName, "line": e.Line, "known_artex": e.KnownARTEX, "source_ambiguous": e.SourceAmbiguous, "raw_excerpt": certClip(e.Raw, 4096), "raw_truncated": len(e.Raw) > 4096, "timestamp": e.Timestamp})
		}
		return jsonResult(rows)
	})
}

func (r *investigatorRun) observationTool() actool.CoreTool {
	return writeTool("record_observation", "Record AI observations, inferences, and data shortages. Use observed only for actions recorded directly in the raw_previews or read_evidence provided. inferred requires normal alternatives and verification methods. You cannot cite evidence that does not exist or has not been read in this exercise.", certObject(map[string]any{"kind": map[string]any{"type": "string", "enum": []string{"observed", "inferred", "insufficient_data"}}, "summary": str("What the evidence directly says and the scope of interpretation"), "evidence_refs": certArray("Actually confirmed event ref"), "alternatives": certArray("Normal behavior/other interpretation and possibility of falsification"), "next_steps": certArray("Improvement of insufficient logs and next investigation/detection")}, "kind", "summary"), func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
		if ctx.Err() != nil {
			return actool.Errorf("Investigation is closed"), nil
		}
		var a struct {
			Kind         string   `json:"kind"`
			Summary      string   `json:"summary"`
			EvidenceRefs []string `json:"evidence_refs"`
			Alternatives []string `json:"alternatives"`
			NextSteps    []string `json:"next_steps"`
		}
		if certDecode(in, &a) != nil {
			return actool.Errorf("Observation input format is incorrect"), nil
		}
		r.mu.Lock()
		defer r.mu.Unlock()
		if len(r.report.Observations) >= 24 {
			return actool.Errorf("Observation record limit has been reached"), nil
		}
		if a.Kind != "observed" && a.Kind != "inferred" && a.Kind != "insufficient_data" {
			return actool.Errorf("Observation type not supported"), nil
		}
		if strings.TrimSpace(a.Summary) == "" || len(a.Summary) > 1600 || certStrings(a.Alternatives, 6, 500) != nil || certStrings(a.NextSteps, 6, 500) != nil {
			return actool.Errorf("Observation is empty or exceeds limit"), nil
		}
		if err := r.validateRefs(a.EvidenceRefs, a.Kind != "insufficient_data"); err != nil {
			return actool.Errorf(err.Error()), nil
		}
		if a.Kind == "inferred" && len(a.Alternatives) == 0 {
			return actool.Errorf("Inferences must leave normal alternatives or alternative interpretations"), nil
		}
		if a.Kind == "insufficient_data" && len(a.NextSteps) == 0 {
			return actool.Errorf("In case of lack of data, you must leave the necessary log or next investigation item."), nil
		}
		known := false
		for _, ref := range a.EvidenceRefs {
			if a.Kind == "observed" && !r.rawSeen[ref] {
				return actool.Errorf("Check the original text of the observation evidence first with read_evidence"), nil
			}
			known = known || r.events[ref].KnownARTEX
		}
		if known {
			a.Alternatives = append(a.Alternatives, "The cited evidence includes ARTEX reproduction traffic. This request itself cannot be classified as an external infringement.")
		}
		o := InvestigatorObservation{ID: fmt.Sprintf("observation-%d", len(r.report.Observations)+1), IntentID: r.intentID, Kind: a.Kind, Summary: a.Summary, EvidenceRefs: a.EvidenceRefs, Alternatives: a.Alternatives, NextSteps: a.NextSteps, KnownARTEX: known}
		r.report.Observations = append(r.report.Observations, o)
		r.report.NextSteps = certUniqueStrings(append(r.report.NextSteps, a.NextSteps...))
		if a.Kind == "insufficient_data" {
			r.report.Gaps = certUniqueStrings(append(r.report.Gaps, a.Summary))
		}
		r.emitLocked(InvestigatorProgress{Kind: "observation", Summary: o.Summary, Observation: &o, EvidenceRefs: o.EvidenceRefs})
		return jsonResult(map[string]any{"saved": true, "observation": o, "assessment": "AI interpretation; references validated, semantic claim not independently verified"})
	})
}
