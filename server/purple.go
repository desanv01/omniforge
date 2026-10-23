package server

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"

	"github.com/desanv01/omniforge/db"
)

const maxPurpleRequestBytes = 256 << 10

func (s *Server) registerPurple(mux *http.ServeMux) {
	// The main Handler wraps these routes with requireAuth, like findings.
	s.registerPurpleReplays(mux)
	s.registerPurpleExecutions(mux)
	s.registerSecuritySources(mux)
	s.registerInvestigations(mux)
	mux.HandleFunc("GET /api/exploration/findings/{id}/defense", s.getFindingDefense)
	mux.HandleFunc("PUT /api/exploration/findings/{id}/defense", s.saveFindingDefense)
	mux.HandleFunc("POST /api/exploration/findings/{id}/defense/validations", s.addFindingDefenseValidation)
	mux.HandleFunc("GET /api/purple/overview", s.purpleOverview)
}

func decodePurpleRequest(w http.ResponseWriter, r *http.Request, target any) bool {
	return decodePurpleRequestLimit(w, r, target, maxPurpleRequestBytes)
}

func decodePurpleRequestLimit(w http.ResponseWriter, r *http.Request, target any, limit int64) bool {
	r.Body = http.MaxBytesReader(w, r.Body, limit)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	err := decoder.Decode(target)
	if err == nil {
		var extra any
		if err = decoder.Decode(&extra); err == io.EOF {
			return true
		}
	}
	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		writeErr(w, http.StatusRequestEntityTooLarge, fmt.Sprintf("The request body must be less than or equal to %d KiB", limit/1024))
	} else {
		writeErr(w, http.StatusBadRequest, "Please enter the correct JSON object and fields")
	}
	return false
}

func purpleFindingID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, ok := pathInt(r, "id")
	if !ok || id <= 0 {
		writeErr(w, http.StatusBadRequest, "Please enter the correct vulnerability ID")
		return 0, false
	}
	return id, true
}

func writePurpleError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, db.ErrDefenseExecutionNotFound):
		writeErr(w, http.StatusNotFound, "Defense verification run not found")
	case errors.Is(err, db.ErrDefenseReplayNotFound):
		writeErr(w, http.StatusNotFound, "Log replay history not found")
	case errors.Is(err, db.ErrFindingNotFound):
		writeErr(w, http.StatusNotFound, "No vulnerabilities found")
	case errors.Is(err, db.ErrTaskArchiveState):
		writeErr(w, http.StatusConflict, "Defense verification information for archived jobs cannot be changed")
	case errors.Is(err, db.ErrDefenseConflict):
		writeErr(w, http.StatusConflict, err.Error())
	case errors.Is(err, db.ErrDefenseInvalid):
		writeErr(w, http.StatusBadRequest, err.Error())
	default:
		log.Printf("[purple] database operation failed: %v", err)
		writeErr(w, http.StatusInternalServerError, "Failed to process defense verification information")
	}
}

func (s *Server) getFindingDefense(w http.ResponseWriter, r *http.Request) {
	id, ok := purpleFindingID(w, r)
	if !ok {
		return
	}
	pg := s.pg(w)
	if pg == nil {
		return
	}
	out, err := pg.GetFindingDefense(r.Context(), id)
	if err != nil {
		writePurpleError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) saveFindingDefense(w http.ResponseWriter, r *http.Request) {
	id, ok := purpleFindingID(w, r)
	if !ok {
		return
	}
	var in db.DefensePlanInput
	if !decodePurpleRequest(w, r, &in) {
		return
	}
	pg := s.pg(w)
	if pg == nil {
		return
	}
	out, err := pg.SaveDefensePlan(r.Context(), id, in)
	if err != nil {
		writePurpleError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) addFindingDefenseValidation(w http.ResponseWriter, r *http.Request) {
	id, ok := purpleFindingID(w, r)
	if !ok {
		return
	}
	var in db.DefenseValidationInput
	if !decodePurpleRequest(w, r, &in) {
		return
	}
	pg := s.pg(w)
	if pg == nil {
		return
	}
	out, err := pg.AddDefenseValidation(r.Context(), id, in)
	if err != nil {
		writePurpleError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

func (s *Server) purpleOverview(w http.ResponseWriter, r *http.Request) {
	page, limit := 1, 20
	for _, p := range []struct {
		name   string
		target *int
		max    int
	}{{"page", &page, 1000000}, {"limit", &limit, 100}} {
		if raw := r.URL.Query().Get(p.name); raw != "" {
			n, err := strconv.Atoi(raw)
			if err != nil || n < 1 || n > p.max {
				writeErr(w, http.StatusBadRequest, "Pages must be in the range 1~1000000, display count must be in the range 1~100")
				return
			}
			*p.target = n
		}
	}
	pg := s.pg(w)
	if pg == nil {
		return
	}
	out, err := pg.GetPurpleOverview(r.Context(), page, limit)
	if err != nil {
		writePurpleError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}
