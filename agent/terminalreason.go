package agent

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/Autumn-27/norma/harness"
)

// runTrace retains the latest tool call so an interrupted run can identify the
// operation that was still in flight.
type runTrace struct {
	startedAt time.Time
	id        string
	name      string
	input     string
	at        time.Time
	pending   bool
}

func (t *runTrace) start(id, name, input string) {
	t.id, t.name, t.input, t.at, t.pending = id, name, input, time.Now(), true
}

func (t *runTrace) done(id string) {
	if id == t.id {
		t.pending = false
	}
}

var reasonHint = map[harness.TerminalReason]string{
	harness.ReasonCompleted:         "The model ended the round normally, but did not leave a text summary; the facts and assets are subject to the tool call record of this round.",
	harness.ReasonMaxTurns:          "The upper limit of steps (MaxTurns) is reached: the SDK has executed the closing and written back the facts and assets. The intention will be marked as exhausted for the planner to change direction and continue instead of handling it as a failure.",
	harness.ReasonTimeout:           "The wall clock budget (MaxDuration) of a single run is reached: when the point is reached, the running tool will be interrupted and finished in place, the identified facts and assets will be written back, and the intent will be marked as exhausted",
	harness.ReasonModelError:        "The model or API call fails (network, authentication, current limit, supplier 5xx, etc.), and the intention is marked as blocked after exhaustion of retries - the transport layer failure causes this intention to be basically not detected; check its execution process (get_worker_trace) before deciding to resend or change the method",
	harness.ReasonBlockingLimit:     "The context length reaches the hard limit and the request is intercepted before being sent; the intent granularity should be narrowed or the compression tool should return",
	harness.ReasonPromptTooLong:     "The prompt word is too long and the context compression retries have been exhausted and execution cannot continue.",
	harness.ReasonImageError:        "The current model does not support multi-modal content for this round; please switch to a model that supports vision or avoid the tool returning images",
	harness.ReasonStopHookPrevented: "The Stop hook prevents the current round from ending and then fails to continue; please check whether the task Guard rules are too strict",
	harness.ReasonHookStopped:       "The tool or hook actively stops execution, such as out of bounds target or disabled command; please check the last tool_result interception description",
	harness.ReasonAbortedStreaming:  "Run canceled during model output streaming generation phase",
	harness.ReasonAbortedTools:      "Run was canceled during tool execution phase",
}

// terminalText renders a terminal event with no final text into a compact summary
// and a Markdown detail block.
func terminalText(ctx context.Context, term *harness.Terminal, tr *runTrace) (string, string) {
	reason := term.Reason
	aborted := reason == harness.ReasonAbortedStreaming || reason == harness.ReasonAbortedTools
	// Prompt may return ctx.Err directly without a terminal event. Preserve the
	// cancellation cause instead of falling back to an empty/unknown terminal reason.
	if reason == "" && ctx.Err() != nil {
		aborted = true
	}

	var sum string
	if aborted {
		_, short, _, ok := AbortReason(ctx)
		if !ok {
			short = "Unable to obtain cancellation reason"
		}
		stage := "During execution"
		switch reason {
		case harness.ReasonAbortedStreaming:
			stage = "Model output stage"
		case harness.ReasonAbortedTools:
			stage = "tool execution phase"
		}
		sum = "(Run interrupted:" + short + ";stop at" + stage + progressSuffix(term, tr) + ", not completed)"
	} else if reason == harness.ReasonMaxTurns || reason == harness.ReasonTimeout {
		sum = "(Running budget limit reached(" + string(reason) + "), the facts have been written back" + progressSuffix(term, tr) + ";There is no text summary this time)"
	} else {
		hint := terminalReasonHint(reason)
		sum = "(No text summary, final state " + terminalReasonLabel(reason) + "：" + firstLine(hint, 80) + "）"
	}

	var b strings.Builder
	b.WriteString(sum)
	b.WriteString("\n\n")
	displayReason := terminalReasonLabel(reason)
	fmt.Fprintf(&b, "- **Final state**: `%s` - %s\n", displayReason, terminalReasonHint(reason))
	if aborted {
		code, _, why, ok := AbortReason(ctx)
		if ok {
			fmt.Fprintf(&b, "- **Interruption reason** (`%s`): %s\n", code, why)
		} else {
			b.WriteString("- **Interruption reason**: Unable to obtain; the canceling party may not have attached a named reason via context.WithCancelCause\n")
		}
	}
	if term.Err != nil {
		fmt.Fprintf(&b, "- **Underlying Error**: `%v`\n", term.Err)
	}
	if aborted && strings.TrimSpace(term.Text) != "" {
		b.WriteString("- **Cancel part of the output generated before**:\n\n")
		b.WriteString(term.Text)
		b.WriteString("\n\n")
	}
	if term.Turns > 0 {
		fmt.Fprintf(&b, "- **Executed**: %d wheel model round\n", term.Turns)
	}
	if !tr.startedAt.IsZero() {
		fmt.Fprintf(&b, "- **Time taken to run this time**: %s\n", roundDur(time.Since(tr.startedAt)))
	}
	if u := term.Usage; u.InputTokens+u.OutputTokens+u.CacheReadTokens+u.CacheWriteTokens > 0 {
		fmt.Fprintf(&b, "- **Cumulative token**: input %d / output %d / cache read %d / cache write %d\n",
			u.InputTokens, u.OutputTokens, u.CacheReadTokens, u.CacheWriteTokens)
	}
	if tr.name == "" {
		b.WriteString("- **Tool Call**: This run ended before a tool call was issued.\n")
	} else if tr.pending {
		fmt.Fprintf(&b, "- **Tool being executed at the time of interruption**: `%s` (%s has been run, **No result returned**)\n\n  ```json\n  %s\n  ```\n",
			tr.name, roundDur(time.Since(tr.at)), firstLine(tr.input, 300))
	} else {
		fmt.Fprintf(&b, "- **Last tool before interruption**: `%s` (has returned normally)\n", tr.name)
	}
	return sum, b.String()
}

func terminalReasonLabel(reason harness.TerminalReason) string {
	if reason == "" {
		return "context_canceled"
	}
	return string(reason)
}

func terminalReasonHint(reason harness.TerminalReason) string {
	if hint := reasonHint[reason]; hint != "" {
		return hint
	}
	if reason == "" {
		return "The running context has been cancelled, but no Terminal event is generated under the hood"
	}
	return "Unknown final state; harness may have added TerminalReason, please add reasonHint"
}

func progressSuffix(term *harness.Terminal, tr *runTrace) string {
	var parts []string
	if term.Turns > 0 {
		parts = append(parts, fmt.Sprintf("%d wheel", term.Turns))
	}
	if !tr.startedAt.IsZero() {
		parts = append(parts, roundDur(time.Since(tr.startedAt)))
	}
	if len(parts) == 0 {
		return ""
	}
	return ", has been run " + strings.Join(parts, " / ")
}

func roundDur(d time.Duration) string {
	switch {
	case d < time.Minute:
		return d.Round(100 * time.Millisecond).String()
	case d < time.Hour:
		return d.Round(time.Second).String()
	default:
		return d.Round(time.Minute).String()
	}
}
