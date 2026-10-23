package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/Autumn-27/norma/agentcore"
	"github.com/Autumn-27/norma/llm"
	acperm "github.com/Autumn-27/norma/permission"
	actool "github.com/Autumn-27/norma/tool"
	"github.com/Autumn-27/norma/transcript"
	"github.com/desanv01/omniforge/db"
)

// goalsDefaultTmpl is the built-in EDITABLE body (段 [A]) of the goals-decomposer
// prompt, seeded into agent_prompts. No template vars are used today.
const goalsDefaultTmpl = "You are a penetration testing target decomposer. Your job is to identify the **ultimate result** from user input, not to plan the attack steps.\n\n**The first step (do it before splitting the target): Extract operational constraints**\nIdentify the operator's clear regulations on [what operations can and cannot be done] from the \"task goal/task description\", and call set_constraints to register them one by one (if the description and goal do not involve operation constraints, you do not need to extract the operation constraints):\n- type=deny: prohibited operations (such as \"no port scanning\", \"no write/deletion operations on the production environment\", \"no blasting\", \"no touching a certain subdomain\").\n- type=allow: clearly allow/restrict the scope of operations (such as \"only allow passive reconnaissance\" and \"only target a certain domain name\").\n- Constraint ≠ target, also ≠ attack step: it is the regulation of the boundaries of operational behavior.\n- **Constraints must be [self-contained, hard-coded specific goals]**: Replace **referential words** such as \"current target/current port/current IP/current domain name/this site\" with **specific values** in the task goal/description. Constraints will be injected separately into the prompts in the execution phase, and it is impossible to determine who the referent refers to after being separated from the context.\n  Example: The target is https://abc.example.net → write \"Only allow testing abc.example.net\" instead of \"Only allow testing of the current target\"; \"Only test target port 443, do not scan other ports\" instead of \"Only test the current port\". If the original text only says \"current target\" but the target address is clear, fill in the address.\n- **Only register the constraints [clearly written or emphasized] in the target/description, and it is strictly forbidden to make up**; use deny (more conservative) when you are not sure about the type.\n- Don't call set_constraints if there are indeed no operational constraints in the target/description.\nAfter registering the constraints (if any), proceed with the following target splitting.\n\n**Goal = Final deliverable/verifiable result**\n\n**Content that is not a goal (not allowed as a sub-goal)**:\n- Information collection, reconnaissance, endpoint scanning\n- Vulnerability analysis and verification process\n- Attack steps and exploitation methods\n- Result verification steps\n\n**Split Principle**:\n- There is only one ultimate goal described by the user → output one\n- There are multiple **mutually independent** final deliverables → listed separately\n- Mark vulnclass that can correspond to a clear vulnerability class; leave information collection/business logic targets blank\n- It is strictly prohibited to invent goals that have not been mentioned by the user\n\nCall set_goals to submit the results."

// goalsScopeTail is the code-owned tail appended after the editable goals body
// WHEN an asset store + task context are available. It teaches the decomposer to
// also lift the explicit asset scope out of the goal/description and register it
// via add_task_scope. Kept in code (not the DB-editable body) so it always applies
// on released DBs and can't be edited away — same pattern as the trafficTool tail.
const goalsScopeTail = "\n\n**Additional Responsibilities: Register Test Asset Scope**\nIn addition to splitting the goals, you must also identify the **clearly given test asset scope** from the \"task goal/task description\" and call add_task_scope to register (the authorization boundary of this task is also the denominator of the asset test coverage). ** Minimum scope principle: Only register the target that the user has clearly clicked on, and never enlarge it without authorization. **\n- The target is a URL or an address with a hostname (e.g. https://xxx.example.com/path、app.example.com）→, take its **full hostname**, kind=subdomain, value=full hostname.\n  Example: target https://a1b2c3.lab.example.net/path → kind=subdomain, value=a1b2c3.lab.example.net (**not** example.net).\n  **It is strictly prohibited** to shorten the host name with subdomains to the root domain name - registering the entire example.com when you see xxx.example.com will expand the scope beyond the user's target, violating the principle of minimum scope.\n- Use kind=root_domain, value=example.com only when the user gives a **bare root domain name and does not include any subdomain** (such as writing example.com directly), or explicitly says \"entire site/all subdomains/full domain name\" →.\n- Pure IP or network segment → kind=ip/cidr, value=IP or CIDR.\n- **Don't** register the company scope (company) - the task has just been created and the company usually does not exist in the asset system, so it cannot be registered, and the company-level scope will be processed in the subsequent plan stage.\nOther rules:\n- Only register the scope of the target/description that is clearly stated; inventing or inferring unmentioned domain names/IPs is strictly prohibited.\n- reason briefly states which sentence the basis comes from to facilitate auditing.\n- **Don't** call add_task_scope without any explicit asset scope in the target/description.\nFirst use add_task_scope to register the scope (if any), and then call set_goals to submit the goal."

// goalsSystem assembles the goals-decomposer system prompt: the rendered body
// [A] (DB-overridable), the code-owned scope-extraction tail when add_task_scope
// is wired (withScope), and the code-owned Korean output-language tail [C] last —
// mirroring chatSystem/plannerSystem so a DB-edited body can never drop the tail.
// DecomposeGoalsWithProvider and the localization test share this one assembly, so
// the langDirective tail can't drift between runtime and test. EngagementDescription
// is intentionally left empty: the task description rides in the user message, not
// the {{.EngagementDescription}} var (see DecomposeGoalsWithProvider).
func goalsSystem(dataDir string, withScope bool) string {
	sys := renderSystem("goals", goalsDefaultTmpl, GoalsVars{DataDir: dataDir, Now: nowStr()})
	if withScope {
		sys += goalsScopeTail
	}
	return sys + langDirective()
}

// GoalSpec is one decomposed objective.
type GoalSpec struct {
	Text      string `json:"text"`
	VulnClass string `json:"vulnclass,omitempty"`
}

// DecomposeGoals asks the LLM to break a pentest task goal into discrete,
// independently-verifiable objectives (each becomes a goal node). Returns nil if
// no provider is configured or the call yields nothing — the caller then falls
// back to a rule-based split so goal nodes always exist.
//
// prov is supplied by the caller (rather than built here from a Config) so goal
// decomposition rides the SAME provider instance as the rest of the engine — it
// shares the rate limiter, gets recorded by llmrec, and participates in LLM
// failover instead of quietly bypassing all three.
//
// desc is the task's free-text description (背景：靶标范围/flag 数量/交战说明等).
// It is fed alongside the goal so the decomposer no longer splits blind — the
// prompt still forbids inventing anything the two texts don't state.
//
// emit, when non-nil, receives every LLM step (thinking/tool_use/result) with
// Worker="planner" so the round-0 goal-decomposition activity is visible in the UI.
//
// as + taskID, when non-nil/positive, wire the add_task_scope tool so the
// decomposer can register the explicit asset scope it extracts from the goal.
//
// ts is the task's exploration store: set_goals writes the decomposed goal nodes
// straight into it (the same managed tool the main agent uses to add goals at
// runtime). The returned specs are read back from the store so callers can emit
// per-goal activity and detect the "LLM produced nothing" case for their fallback.
func DecomposeGoals(ctx context.Context, prov llm.Provider, dataDir, goalText, desc string, as *db.AssetStore, ts *db.ExplorationStore, taskID int64, emit func(db.Activity)) []GoalSpec {
	if prov == nil {
		return nil
	}
	return DecomposeGoalsWithProvider(ctx, prov, dataDir, goalText, desc, as, ts, taskID, false, 0, emit)
}

// DecomposeGoalsWithProvider is the task-runtime variant used when a task has an
// ordered provider chain. It preserves the same tools and write behavior while
// letting the caller own provider selection/failover. maxTokens is the profile's
// per-reply output cap (0 = send none).
func DecomposeGoalsWithProvider(ctx context.Context, prov llm.Provider, dataDir, goalText, desc string, as *db.AssetStore, ts *db.ExplorationStore, taskID int64, nonStreaming bool, maxTokens int, emit func(db.Activity)) []GoalSpec {
	if prov == nil {
		return nil
	}
	// 目标拆解是一次性调用：不挂 transcript store，所以 agentcore 不会往 ctx 上挂
	// session id（它只在有 writer 时才挂，见 agentcore.Prompt）。而按 session-id 头
	// 做提示缓存/粘性路由的网关（opencode zen 缺 x-opencode-session 直接 400
	// MissingSessionID）读的就是 ctx 上这个值——不补就是「对话正常、拆解 400」。
	// 显式挂一个稳定 id：同一探索的拆解请求共享它（利于命中缓存），且命名与
	// planner/worker 不冲突，能被 llmrec.parseSession 正确归因。
	if ts != nil {
		ctx = transcript.WithSessionID(ctx, fmt.Sprintf("exp%d-goals", ts.ID()))
	}
	// worker="goals" tags the goal nodes' provenance; ts/taskID let set_goals link
	// each goal under the task root. This is the catalog's real set_goals tool, so a
	// web-edited description/schema on it applies here too.
	tsx := &ToolSet{as: as, ts: ts, taskID: taskID, worker: "goals"}
	// Wire add_task_scope only when we have a real asset store + task to write to.
	// goalsSystem appends the scope-extraction tail in lockstep (withScope) so the
	// prompt never asks for a tool that isn't present, and it owns the output-language
	// tail last so a DB-edited body can't drop it. Description rides in the user
	// message, NOT the {{.EngagementDescription}} var, so a prompt can't inject it twice.
	withScope := as != nil && taskID > 0
	sys := goalsSystem(dataDir, withScope)
	// set_constraints 始终可用(不依赖 asset store):正文已含「先抽操作约束再拆目标」这步
	// (可在 agent 编辑页改措辞),这里只需接上工具。
	tools := []actool.CoreTool{tsx.setGoals(), tsx.setConstraints()}
	if withScope {
		tools = append(tools, tsx.addTaskScope())
	}
	userMsg := "Mission objectives:\n" + goalText
	if d := strings.TrimSpace(desc); d != "" {
		userMsg += "\n\nMission description (background information, may include target range/number of flags/engagement instructions; for reference only, do not infer content not mentioned in it):\n" + d
	}
	// Use captureRun so every LLM step is emitted as an activity record (visible in
	// the plan tab under the round-0 marker). Falls back gracefully when emit is nil.
	captureEmit := func(r db.Activity) {
		if emit != nil {
			r.Worker = "planner"
			emit(r)
		}
	}
	captureRun(ctx, agentcore.Options{
		Provider:               prov,
		SystemPrompt:           []string{sys},
		Tools:                  tools,
		PermissionMode:         acperm.ModeBypass,
		DisableBackgroundTasks: true,
		// 3 步(抽约束 → 登记范围 → 拆目标)各需一次工具调用,给足回合避免收尾前漏调 set_goals。
		MaxTurns:     8,
		NonStreaming: nonStreaming, // 该 profile 选非流式时走 Provider.Complete
		MaxTokens:    maxTokens,    // 0 = 不发上限,由服务端默认值决定
	}, userMsg, captureEmit)
	// set_goals persisted the goals directly; read them back so the caller sees what
	// was written (empty slice ⇒ the LLM produced nothing ⇒ caller falls back).
	if ts == nil {
		return nil
	}
	nodes, _ := ts.ListByKind(db.KindGoal, 10000)
	var out []GoalSpec
	for _, n := range nodes {
		var p struct {
			Text      string `json:"text"`
			VulnClass string `json:"vulnclass"`
		}
		_ = json.Unmarshal(n.Payload, &p)
		if strings.TrimSpace(p.Text) != "" {
			out = append(out, GoalSpec{Text: p.Text, VulnClass: p.VulnClass})
		}
	}
	return out
}
