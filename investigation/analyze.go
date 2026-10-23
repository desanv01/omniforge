package investigation

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
)

// Analyze links every observation to selected evidence. Follow-on hypotheses
// require domain-specific evidence and remain manual review in this version.
func Analyze(plan Plan, scope Scope, c Collection) Analysis {
	a := Analysis{EngineVersion: EngineVersion, Hypotheses: []HypothesisResult{}, Timeline: []TimelineEntry{}, Signals: []Signal{}, Limitations: append([]string{}, c.Warnings...), NextSteps: []string{}}
	a.Limitations = append(a.Limitations, "An observed event is not a confirmation of a breach. Even if there are no search results, we cannot rule out attacks outside the scope of our investigation.", "HTTP status codes and permission actions alone do not determine successful file delivery, code execution, account takeover, or blocking.")
	events := append([]Event{}, c.Events...)
	sort.SliceStable(events, func(i, j int) bool {
		if events[i].Timestamp.Equal(events[j].Timestamp) {
			return events[i].Ref < events[j].Ref
		}
		return events[i].Timestamp.Before(events[j].Timestamp)
	})
	pathRefs := []string{}
	groups := map[string][]Event{}
	missingIdentity, missingCompletion := 0, 0
	for _, e := range events {
		label := "Recorded Path: " + e.Path
		if e.Path == "" {
			label = "Target-related events without a path — additional fields need review"
		}
		if e.KnownARTEX {
			label = "Known ARTEX verification marks · " + label
			a.KnownARTEXCount++
		}
		a.Timeline = append(a.Timeline, TimelineEntry{Timestamp: e.Timestamp, EvidenceRef: e.Ref, EventID: e.ID, Summary: label, KnownARTEX: e.KnownARTEX})
		if e.KnownARTEX {
			continue
		}
		a.ObservedCount++
		if e.Session == "" && e.SourceIP == "" {
			missingIdentity++
		}
		if e.ResponseComplete == nil || e.Bytes == nil {
			missingCompletion++
		}
		if e.Path == "" {
			continue
		}
		pathRefs = append(pathRefs, e.Ref)
		if e.EventKind == "alert" || e.EventKind == "alarm" || e.SourceAmbiguous {
			continue
		}
		identity := ""
		if e.Session != "" {
			identity = "session=" + e.Session
		} else if e.SourceIP != "" {
			identity = "source_ip=" + e.SourceIP
		}
		if identity == "" {
			continue
		}
		source := e.Source
		if source == "" {
			source = e.FileName
		}
		target := strings.ToLower(e.Target)
		if target == "" {
			target = scope.Target
		}
		// Source and target are separate from identity; a repeated IP in two
		// sources is never treated as a common actor or causal chain.
		keyBytes, _ := json.Marshal([]string{source, target, identity})
		key := string(keyBytes)
		groups[key] = append(groups[key], e)
	}
	if missingIdentity > 0 {
		a.Limitations = append(a.Limitations, fmt.Sprintf("The request flow cannot be bundled because event %d does not have a session or source.", missingIdentity))
	}
	if missingCompletion > 0 {
		a.Limitations = append(a.Limitations, fmt.Sprintf("Event %d does not have all response completed and transmitted byte data, so the actual delivery range cannot be determined.", missingCompletion))
	}
	if a.KnownARTEXCount > 0 {
		a.Limitations = append(a.Limitations, "Markers that matched the saved ARTEX execution UUID were marked separately in the timeline and excluded from the suspect flow. The header marker itself does not authenticate the identity of the requester.")
	}
	keys := make([]string, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	sequenceRefs := []string{}
	signalOverflow := false
	for _, key := range keys {
		g := groups[key]
		found := false
		for start := 0; start < len(g) && !found; start++ {
			paths := map[string]bool{}
			refs := []string{}
			ids := map[string]bool{}
			for end := start; end < len(g) && !g[end].Timestamp.After(g[start].Timestamp.Add(10*time.Minute)); end++ {
				e := g[end]
				p, _ := normalizedPath(e.Path)
				base := strings.TrimRight(scope.PathPrefix, "/")
				if p == base || p == base+"/" {
					continue
				}
				if ids[e.ID] {
					continue
				}
				ids[e.ID] = true
				paths[p] = true
				refs = append(refs, e.Ref)
			}
			if len(paths) >= 2 {
				if len(a.Signals) >= 50 {
					signalOverflow = true
					found = true
					continue
				}
				var keyParts []string
				_ = json.Unmarshal([]byte(key), &keyParts)
				shownKey := strings.Join(keyParts, " · ")
				a.Signals = append(a.Signals, Signal{Kind: "multi_path_requests", Key: shownKey, Summary: fmt.Sprintf("%d events were observed on different routes within 10 minutes from the same log source/destination/session or origin. Normal resource loading/shared IP are also possible explanations.", len(paths)), EvidenceRefs: refs})
				sequenceRefs = append(sequenceRefs, refs...)
				found = true
			}
		}
	}
	if signalOverflow {
		a.Limitations = append(a.Limitations, "The 50 request flow display limit has been exceeded. Narrow down the period and route and conduct further research.")
	}
	for _, h := range plan.Hypotheses {
		r := HypothesisResult{HypothesisID: h.ID, Status: "manual_review", Summary: "This follow-up hypothesis requires separate logarithms and validation conditions. Currently not verified by automated analysis.", EvidenceRefs: []string{}, NextSteps: append([]string{}, h.NextSteps...)}
		switch h.ID {
		case "path_access":
			if len(pathRefs) > 0 {
				r.Status = "observed"
				r.Summary = fmt.Sprintf("Event %d was observed in the selected asset/period/path range. We do not determine the success of an exploit based on path history alone.", len(pathRefs))
				r.EvidenceRefs = pathRefs
			} else if !c.Complete {
				r.Status = "insufficient_data"
				r.Summary = "There are gaps in collection or parsing that make it impossible to draw conclusions about unobserved observations."
			} else if a.ObservedCount > 0 {
				r.Status = "insufficient_data"
				r.Summary = "There is a target event, but there is no request path, so it is not possible to check whether the vulnerable path is accessed."
			} else {
				r.Status = "not_observed"
				r.Summary = "No relevant pathway events other than known ARTEX markers were observed in the identified survey range. This does not mean that there was no infringement."
			}
		case "multi_path":
			if len(sequenceRefs) > 0 {
				r.Status = "suspicious"
				r.Summary = "There are multiple short-duration route request flows that require review. This does not indicate successful file collection or confirmation of the same attacker."
				r.EvidenceRefs = sequenceRefs
			} else if !c.Complete || missingIdentity > 0 || a.ObservedCount > len(pathRefs) {
				r.Status = "insufficient_data"
				r.Summary = "Multi-path request flows cannot be fully evaluated due to collection gaps or lack of sessions, origins, or paths."
			} else {
				r.Status = "not_observed"
				r.Summary = "We have not observed multi-path flows within 10 minutes of the same log source/destination/session or origin in the current range."
			}
		}
		a.Hypotheses = append(a.Hypotheses, r)
	}
	if scope.PathPrefix == "" || scope.PathPrefix == "/" {
		a.Limitations = append(a.Limitations, "No specific vulnerable path is specified. This is a path observation of the entire asset, and its relevance to vulnerabilities must be confirmed separately.")
	}
	a.Summary = fmt.Sprintf("Isolated event %d in scope and known ARTEX verification marker %d. Infringement is determined based on observation and additional investigation.", a.ObservedCount, a.KnownARTEXCount)
	if !c.Complete {
		a.Summary += " Due to gaps in collection, unobserved observations cannot be confirmed."
		a.NextSteps = append(a.NextSteps, "Resolve the collection warning and resubmit evidence for the same asset/period.")
	}
	if len(a.Signals) > 0 {
		a.NextSteps = append(a.NextSteps, "Check whether the multi-path flow is normally used or inspected with the original log and operation history.")
	}
	a.NextSteps = append(a.NextSteps, "Check the conditions for each hypothesis and any additional logs required.", "Review detection rules that match the identified behavior and verify their effectiveness against existing defense verification.")
	return a
}
