# AegisLoop source analysis and first implementation scope

The initial analysis reference is `a530a22` of the local ARTEX-KO extension. The connection points of the independent events, offline evaluation, and actual execution loops added later are also recorded. It does not mean that you have verified the latest implementation of the upstream repository. Reuse existing diagnostic, defense verification, and breach investigation capabilities.

## actual execution structure

| role | Confirmed sources and connections |
|---|---|
| Web·API | Next.js static export → Go binary built-in UI. `Handler` of [`server/server.go`](../server/server.go) registers the API with authentication applied. |
| run task | [`server/engine.go`](../server/engine.go)'s `Engine.Run` → `plannerLoop` / `workerLoop` → `Planner.Plan` / `Worker.Execute` or `ExecuteWithMessage`. |
| Main Agent | Call `MainAgent.Chat` of [`agent/mainagent.go`](../agent/mainagent.go) from the task dialog. The roles are distinct from those of planning and execution agents. |
| Plan/Tool Execution | [`agent/planner.go`](../agent/planner.go), [`agent/worker.go`](../agent/worker.go) use norma's `agentcore`. Reuse tool configurations from `ToolSet` from [`agent/tools.go`](../agent/tools.go) and from [`agent/tools_insert.go`](../agent/tools_insert.go). |
| Diagnostic results | Delegate storage responsibility to the host as `FindingRecorder` in [`agent/finding_recorder.go`](../agent/finding_recorder.go). Vulnerabilities, assets, and traffic bases remain in the existing DB structure. |
| Defense Verification | [`server/purple_execution.go`](../server/purple_execution.go), [`server/purple_upload.go`](../server/purple_upload.go), [`db/purple_execution.go`](../db/purple_execution.go) associate revalidation runs with file/Splunk collection results. |
| Log collection | Reuse file parser from [`investigation/parse.go`](../investigation/parse.go), scoped Splunk search from [`securitysource`](../securitysource/). |
| AI Breach Investigation | `RunInvestigation` of [`agent/investigator.go`](../agent/investigator.go) → Planner's hypothesis/plan → Worker's inquiry/original confirmation/observation record → Re-plan. It does not convey a set of attack tools. |
| actual execution loop | [`server/closedloop_live.go`](../server/closedloop_live.go) → [`db/closedloop_live.go`](../db/closedloop_live.go) → Execute re-verification of existing ARTEX. [`securitysource/closedloop_rule.go`](../securitysource/closedloop_rule.go) applies structured rules to physical files/Splunk audit evidence. |
| Save/Migrate | [`db/db.go`](../db/db.go) applies built-in [`db/schema.sql`](../db/schema.sql) at startup. An additional schema method that preserves existing tables and encryption credentials. |

The existing `finding_investigations` and `finding_investigation_runs` require vulnerability FK. Therefore, you cannot start an investigation independently from the alarm/log just by moving the menu.

## Reuse and further development

| Category | range |
|---|---|
| Reuse as is | Offensive tasks·Planner·Worker·Tools, vulnerability and traffic basis, authentication, LLM settings, file parser, Splunk connection, limited investigation engine. |
| Minimum modification | The existing web menu is organized into an integrated overview, Offensive, Defensive, and Closed-loop. Maintains the existing dashboard and detailed page path and provides a separate Offensive overview. |
| New | Defense events generated without vulnerabilities, immutable log snapshots and AI execution records for each event, separate data evaluation of rule candidates, a pair of actual re-verifications and observation/rule revision, and original export. |

The connection keys for the original implementation are `finding_id` (optional), `case_id` (optional), evaluation iteration ID, and original SHA-256. Links link to relevant evidence and do not automatically prove that the log originated from an actual attack execution.

The actual execution loop stores the original `finding_id`, baseline/current defense execution ID, different verification UUID and revalidation time interval. Check the change status of the original plan/reason and log connections, and connect observations to the current rule revision and log SHA-256. Baseline/candidate shadow results calculated from the same audit log of existing alerts and new reruns are kept separately. Automatic deployment of candidates from production SIEMs is not included in this API.

## UI Selection

Select an existing Next.js UI extension. You can reuse login, permission, configuration, static deployment, and components, and avoid the cost of synchronizing authentication, type, and deployment between the two frontends. The API and storage structure of each task are separated, allowing independent testing. The existing Offensive dashboard is `/offensive`, the Integrated Overview is `/dashboard`, the Independent Incident is `/defensive`, and the Assessment History is `/closed-loop`.

## This MVP and follow-up requirements

This implementation provides **independent incident investigation, offline rule improvement evaluation, and a user-initiated actual execution loop**. The actual loop is: Revalidate baseline ARTEX → Real files/Splunk evidence → Improve candidates from baseline audit logs → Revalidate new UUID → Compare evidence. One loop freezes into two executions, distinguishing between real alerts and shadow rule matches. Two attacks do not yield precision/recall/FPR/MTTD/MTTR.

In the existing log rule evaluation tab, candidates are created by looking at only the improvement data, and TP/FP/TN/FN and precision/recall/FPR are calculated by applying the standard and candidate rules to the same evaluation data, respectively. Repeated or identical improvement/evaluation events are rejected, and indicators without a denominator are left as `null`. Do not use the synthetic example numbers in this tab as performance numbers for an actual run loop.

The following items require separate implementation and verification. We do not assume that a dedicated feature has been implemented just because there is an existing general-purpose tool implementation.

- Code·binary analysis, structured adapter of Scanner·Fuzzer and execution evidence contract.
- Vulnerability benchmark with correct answers, attack path/PoC reproducibility, and diagnostic false positive evaluation.
- Rule validation and production system deployment approval using Sigma·Suricata execution engine.
- An evaluation that specifies the denominator and scenario range of ATT&CK coverage.
- Alert Triage based on actual alert reception, operational response playbook, and MTTR measurement.
- Automation that reflects evaluation results in offensive plans through policy and approval.

This rule comparison is a limited JSON field matcher and is not a replacement for running Sigma·Suricata. The correctness of the label relies on uploader verification. Because evaluation data is also repeatedly reported and rule adjustments are used to make improvements, the study's final performance claims must be re-validated with separate unused data.

Cyber ​​Range and Juice Shop are separate labs. The basic product installation maintains two services: ARTEX and PostgreSQL. AWS is a temporary environment for demonstrating real-world behavior and collecting traces, and separates long-term service infrastructure operations from product goals.
