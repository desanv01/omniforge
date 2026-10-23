package server

import (
	"context"
	"sync/atomic"
	"testing"

	"github.com/Autumn-27/norma/llm"
)

// 空转回合(仅思考、无正文无工具)的识别与续跑，见 steerHooks.Stop。

func assistantThinking(text string) llm.Message {
	return llm.Message{Role: llm.RoleAssistant, Content: []llm.ContentBlock{
		{Type: llm.BlockThinking, Thinking: text, Signature: "sig"},
	}}
}

func TestIsThinkingOnlyTurn(t *testing.T) {
	toolUse := llm.Message{Role: llm.RoleAssistant, Content: []llm.ContentBlock{
		{Type: llm.BlockThinking, Thinking: "Scan the port first"},
		{Type: llm.BlockToolUse, ID: "t1", Name: "run_nuclei"},
	}}
	cases := []struct {
		name string
		msgs []llm.Message
		want bool
	}{
		{"just think", []llm.Message{llm.UserText("start"), assistantThinking("Think about it")}, true},
		{"Thinking + Tools", []llm.Message{llm.UserText("start"), toolUse}, false},
		{"Thoughts + text", []llm.Message{assistantThinking("Think about it"), {
			Role:    llm.RoleAssistant,
			Content: []llm.ContentBlock{{Type: llm.BlockThinking, Thinking: "x"}, llm.TextBlock("in conclusion")},
		}}, false},
		{"Text only has whitespace characters", []llm.Message{{
			Role:    llm.RoleAssistant,
			Content: []llm.ContentBlock{{Type: llm.BlockThinking, Thinking: "x"}, llm.TextBlock("  \n ")},
		}}, true},
		{"Completely empty assistant round", []llm.Message{{Role: llm.RoleAssistant}}, true},
		// 工具结果是 user 角色，判定必须回溯到它前面那条 assistant，而不是就近误判。
		{"The last item is the tool result", []llm.Message{toolUse, {
			Role:    llm.RoleUser,
			Content: []llm.ContentBlock{{Type: llm.BlockToolResult, ToolUseID: "t1"}},
		}}, false},
		{"No assistant messages", []llm.Message{llm.UserText("start")}, false},
		{"empty history", nil, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := isThinkingOnlyTurn(c.msgs); got != c.want {
				t.Fatalf("isThinkingOnlyTurn = %v, want %v", got, c.want)
			}
		})
	}
}

// fakeHooks 是一个可编程的 inner HookRunner，用来验证 steerHooks 对 inner 决定的尊重。
type fakeHooks struct {
	prevent  bool
	blocking []string
	msg      string
}

func (f fakeHooks) PreToolUse(context.Context, string, []byte) (bool, string, []byte) {
	return false, "", nil
}
func (f fakeHooks) PostToolUse(context.Context, string, []byte, []byte, bool) {}
func (f fakeHooks) Stop(context.Context, []llm.Message) (bool, []string, string) {
	return f.prevent, f.blocking, f.msg
}

func TestSteerHooksStopNudgesEmptyTurn(t *testing.T) {
	empty := []llm.Message{assistantThinking("I should enumerate subdomains first")}

	t.Run("Inject continue command into idling round", func(t *testing.T) {
		h := steerHooks{nudges: &atomic.Int64{}, limit: defaultEmptyTurnNudges, label: "worker-1 · #1"}
		prevent, blocking, _ := h.Stop(context.Background(), empty)
		if prevent {
			t.Fatal("Idle rounds should not be hard stopped")
		}
		if len(blocking) != 1 || blocking[0] != emptyTurnNudge {
			t.Fatalf("blocking = %v, want [emptyTurnNudge]", blocking)
		}
	})

	t.Run("Do not intervene when there is text or tools", func(t *testing.T) {
		h := steerHooks{nudges: &atomic.Int64{}, limit: defaultEmptyTurnNudges}
		normal := []llm.Message{{
			Role:    llm.RoleAssistant,
			Content: []llm.ContentBlock{llm.TextBlock("Scan completed, no open ports found")},
		}}
		if _, blocking, _ := h.Stop(context.Background(), normal); blocking != nil {
			t.Fatalf("The normal ending was misjudged as idling: %v", blocking)
		}
		if n := h.nudges.Load(); n != 0 {
			t.Fatalf("Should not count when not involved, got %d", n)
		}
	})

	t.Run("Release and end after reaching the upper limit", func(t *testing.T) {
		const limit = 5 // 用户把「空响应重试次数」配成 5
		h := steerHooks{nudges: &atomic.Int64{}, limit: limit}
		for i := 1; i <= limit; i++ {
			if _, blocking, _ := h.Stop(context.Background(), empty); len(blocking) != 1 {
				t.Fatalf("The %d time should still be within the quota, blocking = %v", i, blocking)
			}
		}
		if _, blocking, _ := h.Stop(context.Background(), empty); blocking != nil {
			t.Fatalf("Still injecting after exceeding the upper limit: %v", blocking)
		}
	})

	// 「空响应重试次数」配 -1 = 关掉这层，emptyTurnNudgeLimit 解析成 0。
	t.Run("Do not intervene when configuration is closed", func(t *testing.T) {
		h := steerHooks{nudges: &atomic.Int64{}, limit: 0}
		if _, blocking, _ := h.Stop(context.Background(), empty); blocking != nil {
			t.Fatalf("Closed and still injecting: %v", blocking)
		}
	})

	t.Run("inner determines not to superimpose during a hard stop.", func(t *testing.T) {
		h := steerHooks{inner: fakeHooks{prevent: true, msg: "guard refuses to end"}, nudges: &atomic.Int64{}, limit: defaultEmptyTurnNudges}
		prevent, blocking, msg := h.Stop(context.Background(), empty)
		if !prevent || msg != "guard refuses to end" || blocking != nil {
			t.Fatalf("The hard stop of inner has been rewritten: prevent=%v blocking=%v msg=%q", prevent, blocking, msg)
		}
		if n := h.nudges.Load(); n != 0 {
			t.Fatalf("Giving way to inner should not consume quota, got %d", n)
		}
	})

	t.Run("inner does not overlap when it is about to continue running.", func(t *testing.T) {
		h := steerHooks{inner: fakeHooks{blocking: []string{"Guard’s reason for continuing to run"}}, nudges: &atomic.Int64{}, limit: defaultEmptyTurnNudges}
		_, blocking, _ := h.Stop(context.Background(), empty)
		if len(blocking) != 1 || blocking[0] != "Guard’s reason for continuing to run" {
			t.Fatalf("The continuation message of inner has been rewritten: %v", blocking)
		}
	})

	t.Run("The behavior remains unchanged when no counter is installed.", func(t *testing.T) {
		h := steerHooks{limit: defaultEmptyTurnNudges} // 例如未来其他调用点忘了传 nudges
		if _, blocking, _ := h.Stop(context.Background(), empty); blocking != nil {
			t.Fatalf("Should not be injected when there is no counter: %v", blocking)
		}
	})
}
