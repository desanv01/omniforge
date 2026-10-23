package report

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
	"unicode"

	"github.com/desanv01/omniforge/db"
)

// containsHan 은 문자열에 CJK 한자(중국어)가 섞여 있으면 true 를 돌려준다.
// 한글(unicode.Hangul)·영문·숫자·기호는 한자가 아니므로 걸리지 않는다.
func containsHan(s string) (rune, bool) {
	for _, r := range s {
		if unicode.Is(unicode.Han, r) {
			return r, true
		}
	}
	return 0, false
}

func sampleFindingNode(t *testing.T) *db.Node {
	t.Helper()
	payload, err := json.Marshal(map[string]any{
		"vulnclass": "SQL Injection",
		"name":      "Login Form SQL Injection",
		"severity":  "high",
		"summary":   "Error-based SQL injection identified in login parameters.",
		"evidence":  map[string]string{"poc": "' OR '1'='1"},
	})
	if err != nil {
		t.Fatalf("Payload serialization failed: %v", err)
	}
	return &db.Node{ID: 1, Kind: "finding", Payload: payload}
}

func sampleDBFinding() *db.DBFinding {
	return &db.DBFinding{
		ID:              123,
		VulnClass:       "SQL Injection",
		Name:            "Login Form SQL Injection",
		Severity:        "high",
		Summary:         "Error-based SQL injection identified in login parameters.",
		Evidence:        "' OR '1'='1",
		Status:          "confirmed",
		Report:          "Detailed analysis text.",
		CreatedAt:       time.Date(2026, 10, 4, 2, 30, 0, 0, time.UTC),
		EvidenceVersion: 2,
		TaskDescription: "Demo Target Penetration Testing",
		TrafficBindings: []db.FindingTrafficBinding{
			{
				ID:   9,
				Role: "request",
				Note: "Injection payload transfer point",
				Snapshot: db.TrafficEvidenceSnapshot{
					Method: "POST",
					URL:    "https://sandbox.local/login",
					Status: 200,
				},
			},
		},
	}
}

// TestReportMarkdownLocalized 는 탐색 그래프 보고서(report.Markdown)의 골격이 한국어이고
// 중국어 한자가 전혀 없음을 검증한다.
func TestReportMarkdownLocalized(t *testing.T) {
	out := Markdown(Input{
		Title:       "demo work",
		Goal:        "Sandbox inspection",
		GeneratedAt: time.Date(2026, 10, 4, 2, 30, 0, 0, time.UTC),
		AssetCounts: map[string]int{"host": 2, "url": 5},
		Findings:    []*db.Node{sampleFindingNode(t)},
	})
	if r, ok := containsHan(out); ok {
		t.Fatalf("The Chinese character %q remains in the report skeleton:\n%s", string(r), out)
	}
	for _, want := range []string{
		"# Penetration Test Report: demo work",
		"- **Task Target**: Sandbox inspection",
		"- **Creation Time**:",
		"## Summary",
		"- Confirmed vulnerabilities: **1**",
		"## Vulnerability",
		"**PoC / Proof:**",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("%q is missing in the report skeleton", want)
		}
	}
}

// TestReportMarkdownEmptyLocalized 는 취약점이 없을 때의 안내 문구가 한국어임을 검증한다.
func TestReportMarkdownEmptyLocalized(t *testing.T) {
	out := Markdown(Input{Title: "empty task", GeneratedAt: time.Now()})
	if r, ok := containsHan(out); ok {
		t.Fatalf("The Chinese character %q remains in the blank report:\n%s", string(r), out)
	}
	if !strings.Contains(out, "_There are no vulnerabilities identified at this time._") {
		t.Errorf("Blank report instructions are not in Korean:\n%s", out)
	}
}

// TestFindingsMarkdownLocalized 는 취약점 요약/상세 Markdown 익스포트 골격과 심각도 라벨이
// 한국어이고 중국어 한자가 없음을 검증한다.
func TestFindingsMarkdownLocalized(t *testing.T) {
	f := sampleDBFinding()
	out := FindingsMarkdown([]*db.DBFinding{f}, time.Date(2026, 10, 4, 2, 30, 0, 0, time.UTC))
	if r, ok := containsHan(out); ok {
		t.Fatalf("The Chinese character %q remains in the vulnerability summary report:\n%s", string(r), out)
	}
	for _, want := range []string{
		"# Vulnerability Summary Report",
		"- **Creation Time**:",
		"- **Total Vulnerabilities**: 1",
		"## Summary",
		"| Severity | count |",
		"| Critical |", "| High |", "| Medium |", "| Low |", // 심각도 라벨(UI status.severity 와 동일)
		"## Vulnerability details",
		"- **Type**: SQL Injection",
		"- **Status**: confirmed",
		"- **Affiliation**: Demo Target Penetration Testing",
		"- **Time of discovery**:",
		"**evidence:**",
		"**Detailed Report:**",
		"## Evidence of relevant traffic",
		"Proof version: 2, Number of bindings: 1.",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("%q is missing in the summary report", want)
		}
	}

	single := SingleFindingMarkdown(f, time.Date(2026, 10, 4, 2, 30, 0, 0, time.UTC))
	if r, ok := containsHan(single); ok {
		t.Fatalf("The Chinese character %q remains in the single report:\n%s", string(r), single)
	}
	for _, want := range []string{
		"- **Severity**: high",
		"## outline",
		"## evidence",
		"## Detailed report",
		"[Request message](evidence/123/9/request.http)",
		"[Response message](evidence/123/9/response.http)",
	} {
		if !strings.Contains(single, want) {
			t.Errorf("There is no %q in the single report.", want)
		}
	}
}

// TestFindingsCSVLocalized 는 CSV 익스포트 헤더가 한국어이고 중국어 한자가 없음을 검증한다.
// (BOM 뒤 헤더 행만 한국어면 된다. 데이터 값은 원본 그대로 둔다.)
func TestFindingsCSVLocalized(t *testing.T) {
	raw := FindingsCSV([]*db.DBFinding{sampleDBFinding()})
	out := strings.TrimPrefix(string(raw), "\xEF\xBB\xBF")
	header := strings.SplitN(out, "\n", 2)[0]
	if r, ok := containsHan(header); ok {
		t.Fatalf("The Chinese character %q remains in the CSV header: %s", string(r), header)
	}
	for _, col := range []string{"ID", "name", "category", "severity", "situation", "affiliation work", "time of discovery", "outline", "Traffic Evidence Count", "Traffic Evidence ID"} {
		if !strings.Contains(header, col) {
			t.Errorf("Column %q is missing in CSV header: %s", col, header)
		}
	}
}
