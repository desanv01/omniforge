package sidequestion

import (
	"errors"
	"fmt"
	"testing"
	"unicode"
)

// assertEnglish fails if msg is empty, carries a CJK Han ideograph (= leftover
// untranslated Chinese), or has no Hangul at all. ASCII field names and the
// "1–4000"-style ranges are fine; only Han marks an unlocalized string.
func assertEnglish(t *testing.T, label, msg string) {
	t.Helper()
	if msg == "" {
		t.Fatalf("%s: Empty message", label)
	}
	hangul := false
	for _, r := range msg {
		if unicode.Is(unicode.Han, r) {
			t.Fatalf("%s: Chinese characters remain: %q", label, msg)
		}
		if unicode.Is(unicode.Hangul, r) {
			hangul = true
		}
	}
	if hangul {
		t.Fatalf("%s: Unexpected Korean text: %q", label, msg)
	}
}

// TestSideQuestionOutputsLocalized guards F21: every user-facing side-question
// (곁질문) error and answer-text literal produced by this package must be Korean.
// These surface through /api/.../side-questions into the chat 곁질문 panel, so a
// revert to Chinese here is a user-visible regression and must fail the build.
func TestSideQuestionOutputsLocalized(t *testing.T) {
	assertEnglish(t, "ErrContextBudget", ErrContextBudget.Error())
	assertEnglish(t, "errSideModelInterrupted", errSideModelInterrupted.Error())
	assertEnglish(t, "errSideNoAnswer", errSideNoAnswer.Error())
	assertEnglish(t, "msgSideToolUnavailable", msgSideToolUnavailable)
	assertEnglish(t, "errSideSummaryCallCap", errSideSummaryCallCap.Error())
	assertEnglish(t, "sideSummaryFailedPrefix", sideSummaryFailedPrefix)
	assertEnglish(t, "errSideSummaryIncomplete", errSideSummaryIncomplete.Error())
	assertEnglish(t, "errSideSummaryOverBudget", errSideSummaryOverBudget.Error())
	assertEnglish(t, "errSideHistoryCursor", errSideHistoryCursor.Error())
	assertEnglish(t, "errSideCompactionStalled", errSideCompactionStalled.Error())
}

// TestSideQuestionBudgetSentinelPreserved: localizing the message must not break
// callers that branch on the ErrContextBudget sentinel with errors.Is (see
// context_test.go, which relies on it after the recovery path gives up).
func TestSideQuestionBudgetSentinelPreserved(t *testing.T) {
	if !errors.Is(fmt.Errorf("prepare: %w", ErrContextBudget), ErrContextBudget) {
		t.Fatal("ErrContextBudget Sentinel identification (errors.Is) is broken")
	}
}

// TestSideQuestionBrainPreserved: the agent-brain prompts (the answering
// instruction and the summary instruction) must stay in their benchmarked
// Chinese. BRIEF 현지화 방침은 두뇌 본문을 번역하지 말고 출력 언어만 한국어로
// 강제하라는 것이라, 이 두 프롬프트가 한국어로 바뀌면 벤치마크 동작이 드리프트한다.
func TestSideQuestionBrainPreserved(t *testing.T) {
	for _, c := range []struct{ label, text string }{
		{"instruction", instruction},
		{"summaryInstruction", summaryInstruction},
	} {
		han := false
		for _, r := range c.text {
			if unicode.Is(unicode.Han, r) {
				han = true
				break
			}
		}
		if !han {
			t.Errorf("%s: Brain prompts are no longer in Chinese (risk of benchmark drift)", c.label)
		}
	}
}
