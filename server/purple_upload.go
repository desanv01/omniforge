package server

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/desanv01/omniforge/securitysource"
)

// The wire allowance accounts for JSON escaping. ParseUpload independently
// bounds the actual UTF-8 file bytes and rows; no path or URL is ever opened.
const maxPurpleUploadRequestBytes = 24 << 20

func (s *Server) uploadDefenseExecution(w http.ResponseWriter, r *http.Request) {
	findingID, ok := purpleFindingID(w, r)
	if !ok {
		return
	}
	executionID, ok := defenseExecutionID(w, r)
	if !ok {
		return
	}
	pg := s.pg(w)
	if pg == nil {
		return
	}
	execution, err := pg.GetDefenseExecutionForCollection(r.Context(), findingID, executionID)
	if err != nil {
		writePurpleError(w, err)
		return
	}
	if execution.SourceKind != "file" {
		writeErr(w, http.StatusConflict, "You cannot upload files to a Splunk connection run. Please start a new run with a file association")
		return
	}
	query, windowComplete, err := defenseExecutionWindow(execution, time.Now().UTC())
	if err != nil {
		writeErr(w, http.StatusConflict, err.Error())
		return
	}
	var snapshot struct {
		Config securitysource.FileConfig `json:"config"`
	}
	if json.Unmarshal(execution.SourceSnapshot, &snapshot) != nil {
		writeErr(w, http.StatusConflict, "Failed to read file association settings at runtime")
		return
	}
	select {
	case defenseCollectSlots <- struct{}{}:
		defer func() { <-defenseCollectSlots }()
	default:
		writeErr(w, http.StatusTooManyRequests, "Other evidence gathering is ongoing. Please try again later")
		return
	}
	var input securitysource.FileUpload
	if !decodePurpleRequestLimit(w, r, &input, maxPurpleUploadRequestBytes) {
		return
	}
	evidence, err := securitysource.ParseUpload(snapshot.Config, input, query)
	if err != nil {
		if errors.Is(err, securitysource.ErrInvalid) {
			writeErr(w, http.StatusBadRequest, err.Error())
		} else {
			writeErr(w, http.StatusBadRequest, "Failed to analyze log file. Please check application format and field settings")
		}
		return
	}
	if !windowComplete {
		evidence.Complete = false
		evidence.Warnings = append(evidence.Warnings, "The 60-second observation period after diagnosis has not yet ended. Please re-upload the logs for the entire period afterwards.")
	}
	assessment, err := pg.SaveDefenseAssessment(r.Context(), findingID, executionID, evidence)
	if err != nil {
		writePurpleError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, assessment)
}
