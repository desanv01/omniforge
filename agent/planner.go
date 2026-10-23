package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"

	"github.com/Autumn-27/norma/agentcore"
	"github.com/Autumn-27/norma/llm"
	"github.com/Autumn-27/norma/permission"
	actool "github.com/Autumn-27/norma/tool"
	"github.com/Autumn-27/norma/transcript"
	"github.com/desanv01/omniforge/db"
	"github.com/desanv01/omniforge/intercept"
)

// Planner is the event-driven LLM planner (docs §4.3): each time the asset or
// exploration graph changes (debounced), it reads the exploration route, queries
// assets, judges whether the task goal is met, and emits 0..N exploration intents
// into the frontier. It is the sole intent generator.
type Planner struct {
	findingRecorder   FindingRecorder
	prov              llm.Provider
	model             string
	tx                *transcript.Store                      // raw LLM conversation persistence (nil = off)
	window            int                                    // context window in tokens (for compaction)
	windowFn          func() int                             // optional dynamic task-chain minimum
	maxTurns          int                                    // max agent turns per run (0 = unlimited)
	killWork          func(intentID int64) error             // engine callback to terminate a running work (nil = off)
	steerWork         func(intentID int64, msg string) error // engine callback to steer a running work mid-run (nil = off)
	proxyAddr         string                                 // recording proxy for WebFetch (empty = direct)
	proxyCACert       string                                 // recording proxy's CA cert path (HTTPS verify)
	webSearch         WebSearchOpts                          // web_search tool backend selection (off by default)
	workDir           string                                 // shared work dir (surfaced in prompt as artifact-output target)
	injectConstraints func() bool                            // resolver: inject task operation constraints into system prompt? (nil = yes)
	nonStreamingFn    func() bool                            // resolver: use non-streaming (Complete) path? (nil = streaming)
	noaEnabledFn      func() bool                            // resolver: use experimental noa compaction? (nil = off)
	maxTokensFn       func() int                             // resolver: per-reply output cap (nil/0 = send no cap)
	compactor         *Compactor                             // cold-node compaction (§7); nil = disabled

	// todos keeps ONE plan-scratchpad per task (keyed by exploration id) so the
	// planner's multi-step plan survives across wake-ups — each Plan() is a fresh
	// session, but the shared store lets it record a serial exploit chain once and
	// dispatch it step-by-step over rounds instead of front-loading it in parallel.
	todoMu sync.Mutex
	todos  map[int64]*actool.TodoStore
}

func NewPlanner(prov llm.Provider, model, workDir string, tx *transcript.Store, window, maxTurns int) *Planner {
	return &Planner{prov: prov, model: model, workDir: workDir, tx: tx, window: window, maxTurns: maxTurns, todos: map[int64]*actool.TodoStore{}}
}

func (p *Planner) SetCompactionWindowResolver(fn func() int) { p.windowFn = fn }

// SetCompactor wires the cold-node compactor (cold-digest §7). Called each
// planner wake-up to advance the round counter, maintain cold stamps, and
// (off the hot path) fold cold nodes into digests. nil = feature disabled.
func (p *Planner) SetCompactor(c *Compactor) { p.compactor = c }

// SetNonStreaming wires a resolver deciding whether runs use the non-streaming
// model path (true = non-streaming). nil/unset = streaming (default).
func (p *Planner) SetNonStreaming(fn func() bool) { p.nonStreamingFn = fn }

func (p *Planner) nonStreaming() bool { return p.nonStreamingFn != nil && p.nonStreamingFn() }

// SetNoaEnabled wires a resolver deciding whether runs use the experimental noa
// context-compression mechanism. nil/unset = off (built-in compaction). Read per
// run so the settings toggle takes effect without rebuilding the agent.
func (p *Planner) SetNoaEnabled(fn func() bool) { p.noaEnabledFn = fn }

// SetMaxTokens wires a resolver for the per-reply output cap. nil/unset or 0 =
// send no cap and let the endpoint decide. Read per run, like nonStreaming.
func (p *Planner) SetMaxTokens(fn func() int) { p.maxTokensFn = fn }

func (p *Planner) maxTokens() int {
	if p.maxTokensFn == nil {
		return 0
	}
	return p.maxTokensFn()
}

func (p *Planner) compactionWindow() int {
	if p.windowFn != nil {
		return p.windowFn()
	}
	return p.window
}

// SetProxy points the planner's WebFetch at the recording proxy plus the CA cert
// it trusts to verify HTTPS through it (empty addr = direct).
func (p *Planner) SetProxy(addr, caCert string) { p.proxyAddr, p.proxyCACert = addr, caCert }

// SetWebSearch selects the web_search backend for the planner (off by default).
func (p *Planner) SetWebSearch(o WebSearchOpts) { p.webSearch = o }

// SetConstraintInject wires a resolver deciding whether this task's operation
// constraints get injected into the planner system prompt. Read per round so the
// settings toggle takes effect without rebuilding the agent. nil = inject (default).
func (p *Planner) SetConstraintInject(fn func() bool) { p.injectConstraints = fn }

// wantConstraints reports whether constraint injection is enabled (default yes).
func (p *Planner) wantConstraints() bool { return p.injectConstraints == nil || p.injectConstraints() }

// todoFor returns the task's persistent planning todo store, creating it on first
// use. Shared across all of this task's planner wake-ups.
func (p *Planner) todoFor(expID int64) *actool.TodoStore {
	p.todoMu.Lock()
	defer p.todoMu.Unlock()
	s := p.todos[expID]
	if s == nil {
		s = actool.NewTodoStore()
		p.todos[expID] = s
	}
	return s
}

// SetKillWork wires the engine's per-work terminate callback so the planner's
// kill_work tool can stop a single running worker.
func (p *Planner) SetKillWork(fn func(intentID int64) error) { p.killWork = fn }

// SetSteerWork wires the engine's per-work steering callback so the planner's
// steer_work tool can inject a mid-run course-correction into a running worker.
func (p *Planner) SetSteerWork(fn func(intentID int64, msg string) error) { p.steerWork = fn }

// renderPlannerTodos formats the persistent planning todo for injection into the
// wake-up prompt (empty when there are no todos yet — first wake-up).
func renderPlannerTodos(items []actool.Todo) string {
	if len(items) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("\n\n[Your planning to-do (retained across wake-ups, written by you in the last round)]:\n")
	for _, it := range items {
		mark := map[actool.TodoStatus]string{actool.TodoPending: "☐", actool.TodoInProgress: "▶", actool.TodoCompleted: "✔"}[it.Status]
		if mark == "" {
			mark = "☐"
		}
		b.WriteString(fmt.Sprintf("  %s %s\n", mark, it.Content))
	}
	b.WriteString("Proceed accordingly: only send intentions to the next step [when the previous steps have been completed/the fact it depends on already exists]; use TodoWrite to update the list (mark the steps that have been satisfied by the fact as completed). Do not repeat steps already in pending/in_progress in the manifest.")
	return b.String()
}

// TriggerEvent describes what concretely caused this planning round to fire, so
// the planner looks first at the actual change instead of re-scanning the whole
// overview. Kind:
//
//	"done"    — a worker finished intent IntentID (its output conclusion is fetched).
//	"finding" — a worker reported a finding on intent IntentID (Detail = 摘要).
//	"goal"    — the human (via 主 agent 的 set_goals) added one OR MORE goals in a
//	            single call (Goals = 本次新增的目标文本，1+ 条；set_goals 支持批量).
//	"goal_deleted" — the human deleted a goal from 总览的目标管理 (Detail = 被删目标文本).
//	"goal_edited"  — the human edited a goal from 总览的目标管理 (OldGoal→NewGoal 文本).
//	"cancelled" — the human deleted intent IntentID (Detail = 删除原因). The intent is
//	            stopped (not deleted) and the reason is attached to it as a fact.
type TriggerEvent struct {
	Kind     string
	IntentID int64
	Detail   string
	Summary  string   // Kind=="cancelled" 专用：删除前捕获的意图摘要（真删除后节点已不存在，无法再查）
	Goals    []string // Kind=="goal" 专用：本次 set_goals 新增的目标文本（1 条或多条）
	OldGoal  string   // Kind=="goal_edited" 专用：修改前的目标文本
	NewGoal  string   // Kind=="goal_edited" 专用：修改后的目标文本
	Hints    []string // Kind=="hint" 专用：本次 add_hint 新增的提示文本（1 条或多条）
}

// renderTriggers spells out the change(s) that fired this round: for a finished
// worker — which intent + its output conclusion; for a finding — which intent +
// what was found. Empty for time/heartbeat wakes. Reads the store (best-effort;
// a blank field never blocks the round).
func renderTriggers(ts *db.ExplorationStore, evs []TriggerEvent) string {
	if len(evs) == 0 || ts == nil {
		return ""
	}
	var b strings.Builder
	b.WriteString("\n\n[The actual changes that trigger this round this time (read here first, and then decide whether to supplement the direction)]:")
	for _, ev := range evs {
		switch ev.Kind {
		case "goal":
			if len(ev.Goals) == 1 {
				b.WriteString(fmt.Sprintf("\n- The person (main agent) has added a new target: %s - a new target to be achieved, please supplement the exploration direction accordingly (if there is no corresponding intention yet).", ev.Goals[0]))
			} else {
				b.WriteString(fmt.Sprintf("\n- The person (main agent) added %d goals: %s - all are new goals to be achieved. Please add exploration directions for goals that do not have corresponding intentions one by one.", len(ev.Goals), strings.Join(ev.Goals, "；")))
			}
		case "hint":
			if len(ev.Hints) == 1 {
				b.WriteString(fmt.Sprintf("\n- A new strategic tip has been added to the person (main agent): %s - it has been linked to the exploration map. Please adjust/supplement the exploration direction accordingly (if there is no corresponding intention yet).", ev.Hints[0]))
			} else {
				b.WriteString(fmt.Sprintf("\n- The person (main agent) has added %d strategic tips: %s - all of them have been linked to the exploration map. Please adjust/supplement the exploration direction accordingly.", len(ev.Hints), strings.Join(ev.Hints, "；")))
			}
		case "goal_deleted":
			b.WriteString(fmt.Sprintf("\n- Someone deleted the target: %s - The target has been removed, please re-judge the remaining targets/directions accordingly (no need to assign intentions to it anymore).", ev.Detail))
		case "goal_edited":
			b.WriteString(fmt.Sprintf("\n- The target has been changed from \"%s\" to \"%s\" - please adjust the exploration direction according to the new target (please stop sending if the original direction is no longer applicable).", ev.OldGoal, ev.NewGoal))
		case "finding":
			b.WriteString(fmt.Sprintf("\n- A worker for intent #%d (%s) reported a finding: %s", ev.IntentID, intentSummary(ts, ev.IntentID), ev.Detail))
		case "cancelled":
			// 意图内容优先用删除时捕获的 Summary（真删除后节点已不存在，intentSummary 查不到）。
			sm := ev.Summary
			if sm == "" {
				sm = intentSummary(ts, ev.IntentID)
			}
			b.WriteString(fmt.Sprintf("\n- Intent #%d is deleted by the user, the intent content is: %s, and the reason for deletion is: %s. The intent has been deleted (no longer executed); please plan accordingly.", ev.IntentID, sm, ev.Detail))
		default: // "done"
			b.WriteString(fmt.Sprintf("\n- The worker with intent #%d (%s) ends and outputs the conclusion: %s", ev.IntentID, intentSummary(ts, ev.IntentID), workerOutput(ts, ev.IntentID)))
			if fids := factIDsYielded(ts, ev.IntentID); fids != "" {
				b.WriteString(fmt.Sprintf(";New fact id generated by this intention: %s ", fids))
			}
		}
	}
	b.WriteString("\n(Full details can be found in node_detail / get_worker_output / list_findings.)")
	return b.String()
}

// factIDsYielded lists the fact ids an intent produced this run as "#12、#15", so the
// planner can jump straight to the round's incremental facts. Empty (best-effort) when
// the intent yielded no facts or the lookup fails.
func factIDsYielded(ts *db.ExplorationStore, id int64) string {
	ids, err := ts.FactsYielded(id)
	if err != nil || len(ids) == 0 {
		return ""
	}
	parts := make([]string, len(ids))
	for i, fid := range ids {
		parts[i] = fmt.Sprintf("#%d", fid)
	}
	return strings.Join(parts, "、")
}

// intentSummary reads an intent node's one-line summary (best-effort, "?" on miss).
func intentSummary(ts *db.ExplorationStore, id int64) string {
	n, err := ts.GetNode(id)
	if err != nil || n == nil {
		return "?"
	}
	var p map[string]any
	if json.Unmarshal(n.Payload, &p) == nil {
		if s, ok := p["summary"].(string); ok && s != "" {
			return s
		}
	}
	return "?"
}

// workerOutput returns the finished worker's conclusion for an intent — the last
// 'result' (else 'text') activity's full detail, truncated. Same source get_worker_output uses.
func workerOutput(ts *db.ExplorationStore, id int64) string {
	acts, _, err := ts.ActivityList(&id, 0, 1000)
	if err != nil {
		return "(Failed to get output)"
	}
	var pick *db.Activity
	for i := range acts {
		if acts[i].Kind == "result" {
			pick = &acts[i]
		} else if acts[i].Kind == "text" && pick == nil {
			pick = &acts[i]
		}
	}
	if pick == nil {
		return "(This work has no output records yet)"
	}
	out, _ := ts.ActivityDetail(pick.ID)
	if out == "" {
		out = pick.Summary
	}
	return truncOutput(out, 800)
}

// truncOutput caps a worker-output blob so the trigger context doesn't bloat the
// system prompt every round; full text is one get_worker_output call away.
func truncOutput(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + " …(truncated, see get_worker_output for complete)"
}

// renderGraphOverview folds the pre-computed graph_overview snapshot into the
// wake-up prompt so the planner starts each round with the full situation in
// hand — saving the round-trip it would otherwise spend calling the tool. It is
// the exact same JSON graph_overview would return; deeper detail is still one
// tool call away (node_detail / list_facts / …).
func renderGraphOverview(data map[string]any) string {
	b, err := json.Marshal(data)
	if err != nil {
		return "" // fall back to the model calling graph_overview itself
	}
	return "\n\n[Situation of this round (graph_overview prefetch, equivalent to the return of calling this tool; if you need details, adjust node_detail/list_facts, etc. as needed)]:\n" + string(b)
}

// plannerDefaultTmpl is the built-in EDITABLE body (段 [A]) of the planner prompt,
// seeded into agent_prompts. Goal is a {{.Goal}} template var; the 中间产物输出规约
// tail is code-owned (artifactSpec) and appended by plannerSystem after rendering.
const plannerDefaultTmpl = "You are the \"planner\" of a network security platform authorized penetration testing system and are frequently awakened (as soon as the picture changes). Responsibilities: Read the situation → Determine the target → **Only add exploration intentions when there are new directions that have not been covered**. You are a planner, not an executor: all products in this round can only be [generate/clarify intentions] or [determine goals], and never do the work in the plan.\n\nMission goal: {{.Goal}}\n\n**Several intentions should be produced this round (think about this first)**:\n- **Hard bottom line (highest priority)**: As long as the [goal has not been achieved] and [there is currently no open or running intention] (frontier_open=0 and running_intents is empty), this round [must] produce at least one intention to advance towards the goal - when there is no running work waiting and no direction queued, 0 intentions = task suspension; even if the known direction is only in recent_done, it must be done/exhausted/blocked as follows Judgment to open another or continue to send one.\n- Outside of the hard bottom line, **producing 0 intentions is a normal result, but there must be a valid reason** (not the default of \"less dispatch is more stable\"): ① **covered** - the direction you think of has been processed by the intention that is still open/running (it is a serious mistake to re-generate existing intentions by changing the wording); ② **Waiting for dependencies** - the next step depends on the output of the currently running work, but it has not come out (at this time, the hard-core will make the downstream unable to get the front-end and idle, and should wait until the next wake-up map is updated).\n- On the other hand: If there is indeed a new direction [that is not covered and does not depend on running work], or the goal has not been achieved and there are still untested areas within the scope, then it is time to send it - don't use 0 intentions as the default for laziness.\n\n**Decision-making process for each wake-up**:\n\n1. **The complete situation is attached below this tip** (it is the return of graph_overview, no need to adjust it again): task (original title + target/root node), asset count, goals + status, open/running/recent_done Intent, sites_without_endpoints (sites without endpoints, suggesting possible directions to be explored), facts (number of exploration facts, and vulnerabilities are two types), recent_facts ({id, summary, confidence?}).\n   - **Scope**: The exploration node (goals/intentions/facts/findings) only contains this task; **Asset graph is shared globally** (same copy for multiple tasks, the asset count is global in scope and not unique to this task) - ignore assets that are not related to this task.\n   - **Bloodline**: Each intention has parents (upstream: which facts/intentions are derived from) and yields (downstream: which facts/discoveries are generated), and each recent_facts has from_intent; based on this, we can understand \"which facts come from which direction, and whether a new direction can be synthesized.\"\n   - **Negative/Doubtful Observations** (\"Port closed/cannot be injected\" in recent_facts, etc.) are workers' observations, not final conclusions: check node_detail(id) before accepting evidence - only those with solid evidence, confidence=observed, and exhausted means are considered to be temporarily blocked in this direction; if evidence is missing, it just \"looks like/only explored once\", or confidence=inferred If it is within the scope and is not covered by other intentions, a review intention will be sent to confirm or overturn by default (**The same negative direction can be reviewed at most once**; if it is still negative after review and the evidence is reasonable, the conclusion will be respected and no more will be sent).\n   - **Adjust as needed for deeper details**: list_facts (pagination, latest first, default 20, q filtering, before page turning, with total/has_more), list_findings (all vulnerabilities), node_detail(id) (complete evidence/details; list/recent_facts only gives summary), list_assets (pull: q search, type/company_id/task_id filtering, paging, or id/ids (direct access), asset_neighbors. Assets are shared globally, don’t pull the full amount by default.\n\n2. **Judge goals (core responsibilities)**: The goals field already contains goals and status; for unachieved goals that have been proven by a discovery/fact, call prove_goal(goal_id, evidence_id, reason) to mark met. **When you mark the last unfinished goal, the system automatically determines that the entire task is completed** - the ending is only driven by prove_goal one by one, and there is no other \"one-click completion\" method.\n   - ⚠️ **Quantitative acceptance check (no stamping in advance)**: When the goal contains quantifiable conditions (coverage reaches met. Example: The required coverage is 100% but the actual measured coverage.pct=40% → is not achieved, and the supplementary test intention will continue to be sent.\n\n3. **(optional, only at the beginning, very lightweight) Detection and understanding**: Only when there are almost no facts in the picture (recent_facts is basically empty and the task has just started), and the initial intention cannot be specified based on the situation alone, use Bash, etc. to do a very small amount of read-only detection of the target (such as 1-2 curls to see the homepage/fingerprint). **The only legal product is a more precise description of intent** - not the discovery/verification/exploitation of vulnerabilities, nor the enumeration results of endpoints/directories/parameters (those are the work of workers, written as intent and sent). Three hard boundaries:\n   - There are already facts produced by workers in the picture (facts>0 / recent_facts is not empty) → [Disable] and then detect by yourself. All judgments are based on existing facts. The products of this round can only be \"send new intent\" or \"end\"; if you want to dig deeper into a certain clue → send the intent and let the worker check it, instead of curling it yourself.\n   - Even at the beginning, I will stop probing no more than 3 times, just to make the initial intention clear; once I find that I am \"in-depth verification\" instead of \"quickly determining the direction\" (enumerating endpoints/directories one by one, trying ids one by one, decoding chains, repeatedly probing the same interface, and testing and verifying any injections/privileges/vulnerabilities - all the heavy work of the worker), immediately stop writing the intention.\n   - If it can be judged from the existing facts/situation, there is no need to detect it at all.\n\n4. **Decide which new directions to add**: **\"Restraint\" here only refers to [not repeating existing intentions], not \"send as few as possible\"** - When the goal is not achieved, the default question is \"In order to approach the goal, what are the deeper, more ruthless, and uncovered play methods?\" rather than \"whether it can be concluded.\" The intention is [open exploration direction] (not a fixed type/menu). Combine the known facts, assets, and goals to self-determine the direction, and compare them one by one with open + running + recent_done:\n   - Existing open/running override → no longer generated (processing).\n   - Appeared in recent_done → **First look at the state of the intention (with each item) to determine how to stop, and then decide**:\n     · **done (run normally)**: Covered → not redistributed as it is; whether it is a dead end depends on the fact conclusion produced by yields, not the state; it will only be redistributed when [material new mechanism] (new facts/assets/parameters/obviously different play methods) appears, and the summary clearly states the difference from the last time; changing the wording, \"trying again, maybe it will work\" will not count, and retrying is prohibited.\n     · **exhausted (the budget is exhausted, the detection is cut off in the middle, and only the part is written back) / blocked (the model or network fails, and the detection is basically not completed) **: They are all incomplete and the information is incomplete - first use get_worker_trace / get_worker_output to see where it actually does and where it is stuck, and then choose from the following: close to breakthrough but blocked by the budget → send \"continue with the last progress\"; pure external failure does not work (usually blocked) → Directly redistribute in the same direction; get stuck in the same place every time → change play method/direction. The basis is always the actual progress in the trace, not the state itself.\n   - Completely new direction without any intention to cover → Generate.\n   - All known directions are covered by intentions that are still open/running → not generated and ended directly (there are running/queued work, waiting for them to advance); but if only recent_done is left covered, there is no open/running and the goal is not achieved → press the top hard bottom line and must be opened or renewed.\n   - **Depth takes precedence over coverage**: Coverage is the lower limit/acceptance item, not the exploration target itself; after discovering a high-value entrance (which may lead to RCE/privilege escalation/data leakage), prioritize the intention to penetrate that path [deeper], rather than spreading the coverage and shallowly testing each asset one by one to level the coverage.\n   - **Keep routes diverse and don’t converge too early**: When the goal is not achieved, if existing intentions are crowded on the same route/entrance, and there is an [essentially different] uncovered direction (another entry surface/another type of asset/another utilization chain), give priority to filling that divergent direction instead of adding synonymous intentions on the same line (see the substantive difference, not the wording); if the divergent direction has been covered by existing intentions, it will still not be generated. The ideal is for 2-3 routes with different mechanisms to coexist (such as \"attack from the upload chain\" and \"attack from the authentication bypass\"), and resources will be concentrated only after one of them has handed over evidence of [the target is approaching]. **But diversity always obeys the top [Operation Constraint]**: The entry plane/port/host/operation excluded by the constraint will never generate an intention even if it is essentially different.\n\n   **Serial application chain: send it step by step, don't split it into parallel. ** Strongly dependent serial chain (①→②→③, the next step depends on the actual output of the previous step): do not issue in parallel at once (the downstream will only repeat/idle if it cannot get the prerequisites that do not exist yet); use TodoWrite to record the entire chain as a to-do (one step for each step). This round only sends the step with \"prerequisites satisfied\" (usually the first step). After it produces fact, it wakes up next time (the prompt will bring the to-do list) and then dispatches the next step and marks the satisfied ones as completed. Don't split \"the same thing\" into two (\"confirm trigger point\" and \"trigger trigger point\" are the same step); only the [parallel, independent] dimensions (such as enumerating multiple unrelated endpoints) can use multi-intent parallelism.\n\n5. **Submit**: Use [once] add_intent to batch submit the filtered new directions (intents array, up to 4 highest value ones, do not adjust each item multiple times):\n   - **summary**: One sentence of natural language describes the direction (complete address of test target + what to do + why), without fixed classification; deduplication mainly relies on comparing it with existing intentions.\n   - **asset_ids**: The target asset IDs to be tested/attacked in this direction (try to pass, 0/1/multiple, from list_assets) - must be passed as long as the direction revolves around specific assets (site/interface/parameter/host), used to cover deduplication, connect to asset links, and pass across multiple assets; leave it blank for pure global reconnaissance without specific assets.\n   - **parent_ids**: The upstream nodes from which this direction is synthesized (optional, 0/1/multiple) - if multiple facts are combined to produce an intent, all are passed. If it is derived from an upstream intent/discovery, its id is also passed. The top-level new direction is left blank.\n\nThere is no duplication or imposition; but when the goal is not achieved and there is a deeper play style that is not covered, this faction will be sent. Simple, focused and efficient."

func plannerSystem(goal, dataDir, workDir string) string {
	body := renderSystem("planner", plannerDefaultTmpl, PlannerVars{Goal: goal, DataDir: dataDir, Now: nowStr()})
	return body + artifactSpec(workDir) + langDirective()
}

// Plan runs one planning round. emit, if non-nil, receives the planner's execution
// steps (so users can see how it reads the situation and judges goals — the
// planner is the intent generator and was previously a black box). Returns whether
// the planner judged the goal met.
// triggers carries the concrete change(s) that fired this round — worker(s) done
// and/or finding(s) reported (may be several — the engine debounces a burst; empty
// for time/heartbeat wakes). They are spelled out at the top of the prompt so the
// planner looks first at the actual change (which intent, its output/finding).
func (p *Planner) Plan(ctx context.Context, taskID int64, as *db.AssetStore, ts *db.ExplorationStore, goal string, triggers []TriggerEvent, emit func(db.Activity)) (met bool, reason string, err error) {
	// cold-digest §2.3/§7: advance this task's planner-round counter, maintain the
	// cold_since_round stamps, and (if a threshold is hit) kick off background
	// compaction. Synchronous part is cheap (a few queries); the LLM compaction
	// runs in a detached goroutine so it never adds latency to this round.
	p.compactor.OnPlannerRound(ctx, ts)
	tsx := NewToolSet(ts, "planner")
	tsx.SetFindingRecorder(p.findingRecorder)
	if as != nil {
		tsx.SetAssetStore(as, as.Companies())
	}
	tsx.SetTaskID(taskID)
	tsx.SetCoverageEnabled(as == nil || as.CoverageEnabled(taskID))
	tsx.killWork = p.killWork   // enable kill_work tool (nil = unavailable)
	tsx.steerWork = p.steerWork // enable steer_work tool (nil = unavailable)
	if origin, _ := ts.OriginFactID(); origin > 0 {
		tsx.SetOwnerNode(origin) // planner-side anchors default to the task root (origin fact)
	}
	// 领域工具 + 基础默认工具集（Read/Write/Edit/MultiEdit/LS/Glob/Grep/Bash）
	// 资产覆盖度功能关闭时剔除 add_task_scope/list_untested_assets（不入 prompt）。
	base := append(tsx.DropCoverageTools(tsx.PlannerTools()), actool.DefaultTools()...)
	ctx = WithRunInfo(ctx, RunInfo{TaskID: taskID, ExplorationID: explorationID(ts)})
	tools, def, cleanup := AugmentTools(ctx, "planner", base)
	defer cleanup()
	// 关键态势（刚完成的意图 + 预取的完整图）改放【本轮 user 输入】(见下方 input)，system
	// 只留静态规划正文。move-out 让 system 每轮稳定、更利于缓存；代价是若单轮变长，态势可能
	// 被 compaction 压缩（planner 单轮通常短，风险低）。situational 会拼进下方 input。
	situational := renderTriggers(ts, triggers) + renderGraphOverview(tsx.graphOverviewData())
	// 任务级 deadline / 终局模式(经 ctx 注入,见 taskclock.go)。终局那一轮把任务超时
	// planner 收尾词作为【本轮操作指令】拼进本轮 user 输入(随 situational),让它只做最后
	// 目标判定、不产新意图。
	tc := taskClockFrom(ctx)
	if tc.Final {
		situational += "\n\n[Final ending of the mission (special instructions for this round, covering the regular planning process above)]:" + resolveTaskTimeoutWrapup("planner")
	}
	// 本任务的工作目录 <workDir>/tasks/<taskID>，先建好。
	taskDir := ensureRunDir(p.workDir, taskID, 0)
	ctx = intercept.WithReviewContext(ctx, taskDir, intercept.ReviewBackground{})
	sysBody := plannerSystem(goal, p.workDir, taskDir)
	if p.wantConstraints() {
		sysBody += constraintBlock(ts) // 操作约束(若有)注入系统提示,框定探索边界
	}
	system, boundary := deferredSystem(sysBody, def)
	// planner 无自身墙钟预算;有 deadline 时把 MaxDuration 夹逼到剩余,让在跑的规划轮在
	// 任务到点时进收尾(因超时→任务超时词,因步数→per-run 词)。
	maxDur, clamped := clampMaxDuration(tc.DeadlineUnix, 0)
	settle := wrapupSettlement("planner", nil)
	if tc.DeadlineUnix > 0 {
		settle = wrapupSettlementForTask("planner", nil, clamped)
	}
	opts := agentcore.Options{
		Provider:        p.prov,
		SystemPrompt:    system,
		DynamicBoundary: boundary,
		Tools:           tools,
		DeferredTools:   def.Deferred,
		UnlockSet:       def.Unlock,
		PermissionMode:  permission.ModeBypass,
		EnableWebFetch:  true, // 走记录代理留痕；载入代理 CA 验证 MITM 重签的 HTTPS 证书
		WebFetchProxy:   p.proxyAddr,
		WebFetchCACert:  p.proxyCACert,
		// 联网搜索(可选)。ddgs 无需 key；brave-free 需 BraveKey；tavily 需 TavilyKey。
		// WebSearchProxy 是独立出口代理(http/https/socks5)，与记录流量的 MITM 代理无关；空则直连。
		EnableWebSearch:       p.webSearch.Enabled,
		WebSearchBackend:      p.webSearch.Backend,
		BraveSearchAPIKey:     p.webSearch.BraveKey,
		TavilySearchAPIKey:    p.webSearch.TavilyKey,
		DeepSeekSearchBaseURL: p.webSearch.DeepSeekBaseURL,
		DeepSeekSearchAPIKey:  p.webSearch.DeepSeekAPIKey,
		DeepSeekSearchModel:   p.webSearch.DeepSeekModel,
		WebSearchProxy:        p.webSearch.Proxy,
		BashEnv:               proxyEnv(p.proxyAddr, p.proxyCACert), // Bash 子命令默认走代理+信任 CA
		WorkingDir:            taskDir,                              // 本任务工作目录 <workDir>/tasks/<taskID>
		ToolOutputDir:         cmdOutDir(taskDir),
		MaxTurns:              p.maxTurns, // 0 = unlimited (configurable in agent management)
		MaxDuration:           maxDur,     // 0=不限;有 deadline 时=距 deadline 剩余
		Compaction:            compactionConfig(p.compactionWindow()),
		// 跨唤醒共享的规划待办：让串行链在多轮之间保留（session 是新的，store 不是）。
		Todos: p.todoFor(ts.ID()),
		// 命中【本轮】步数预算→ SDK 跑收尾:把本轮已想清楚的结论落地(该派的 add_intent、
		// 能证的 prove_goal、串行链记 TodoWrite),而非停止规划——planner 之后仍会被反复唤醒。
		// clamped(被任务 deadline 夹逼)时改用 PromptByReason(见 wrapupSettlementForTask)。
		Settlement:   settle,
		NonStreaming: p.nonStreaming(), // 该 profile 选非流式时走 Provider.Complete
		MaxTokens:    p.maxTokens(),    // 0 = 不发上限,由服务端默认值决定
	}
	if p.tx != nil { // persist raw LLM conversation; one accumulating file per task's planner
		opts.Transcript = p.tx
		opts.SessionID = fmt.Sprintf("exp%d-planner", ts.ID())
	}
	// 实验功能:开启后由 noa 接管上下文压缩(归档集中在 <workDir>/noa/<SessionID> 下,持久)。
	noaSession := fmt.Sprintf("exp%d-planner", ts.ID())
	enableNoa(&opts, p.noaEnabledFn, p.workDir, noaSession, noaWarn(noaSession))
	// 态势（刚完成的意图 + 完整图）现在拼进本轮 user 输入（见下方 input）。user 里还有
	// 指令 + 跨唤醒待办（todo 是模型自己的规划便签，可再生，放 user 即可）。
	// 开场白按「本轮有无具体变动」分两种：有变动 → 指向下方【实际变动】块；无变动
	// (心跳定时巡检 / hint / 恢复等) → 别谎称"图发生了变化",转而提示顺带复查在跑意图。
	lead := "There have just been specific changes (see below [Actual changes that triggered this round]), plan the next step accordingly:"
	if len(triggers) == 0 {
		lead = "This round is the wake-up of **scheduled inspection (heartbeat to point)/no specific change signal** - there may not necessarily be new changes in the graph. By the way, review the running intention: if there is no progress or deviation for a long time, use steer_work to correct the deviation; if the direction is completely wrong, use kill_work to stop the loss; then judge the target and decide whether to correct the direction:"
		// 心跳/无变动唤醒时,若全图已无任何 open 或 running 意图 → 探索已停摆(没 worker 在跑、
		// 也没排队方向)。明确告知 planner 并强制其本轮补出新方向,别只复查在跑意图后空转一轮。
		if active, err := ts.HasActiveIntent(); err == nil && !active {
			lead = "This round is the wake-up of scheduled inspection (heartbeat to point), and currently there is no intention to open or run - there are no workers running, and there are no directions in the queue, and exploration has stopped. You **must** produce one or more new intentions in this round that advance toward the goal and are **non-duplicate** with the existing intentions in the picture (0 intentions are not allowed); first determine whether the goal has been achieved based on the following situation, and if not, immediately add the direction:"
		}
	}
	input := lead + situational + "\n\nBased on the above situation, determine the target. When the goal has been [actually achieved] (the target results have been obtained/the target vulnerabilities have been confirmed), use prove_goal to mark them one by one. **Hard bottom line: As long as the goal has not been reached and there is currently no open or running intention (frontier_open=0 and running_intents is empty), this round must produce at least one intention to advance towards the goal - at this time, there is no running work to wait and no direction in the queue. Producing 0 intentions = task suspension. Only when there is already an open/running intention in progress or the goal has been achieved, no new intention can be generated in this round. **" +
		renderPlannerTodos(opts.Todos.List())
	// MaxDuration 现在会在墙钟到点打断在跑工具并就地进收尾(在活 ctx 上),单轮卡死不再
	// 绕过收尾,无需外部硬 ctx 兜底。ctx 只承载 pause / kill / shutdown。
	_, _, err = captureRun(ctx, opts, input,
		func(r db.Activity) {
			if emit != nil {
				r.Worker = "planner" // planner activity has no intent_id (it generates them)
				emit(r)
			}
		})
	return tsx.GoalMet, tsx.Reason, err
}
