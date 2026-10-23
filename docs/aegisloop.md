# AegisLoop usage guide

Connect ARTEX's vulnerability diagnosis and re-verification with actual log evidence, and compare improved rules with baseline audit logs in new attack execution. Independent incident investigation starting without vulnerabilities and evaluation of existing offline rules are also available from the same web app. Please also refer to [Source Analysis and Implementation Scope](aegisloop-source-analysis.md) and [Initial Screen Verification Record](evidence/aegisloop-mvp.md). The synthesis rule evaluation figures from the initial record are not the performance figures of the actual attack loop.

## integrated screen

- `/dashboard`: Actual number of saved records and entry points for Offensive·Defensive·Closed-loop.
- `/offensive`: Traditional diagnostic dashboard. The Tasks, Assets, Vulnerabilities, and Traffic screens maintain their existing paths.
- `/defensive`: Create incidents from files or Splunk logs without vulnerabilities, view results, and AI investigate selected incidents.
- `/closed-loop`: Basic **Actual Execution Loop**, optional **AWS Windows**, and existing **Evaluate Log Rules** tab. HTTP revalidation,distinguishes between static Windows hands-on scenarios and,offline label evaluation. For AWS connection, refer to [Separate Bridge Instructions](aws-windows-loop.md).
- `/function/purple`: Confirmation of detection and blocking linked to re-verification of existing attacks.

LLM connection, log source, permissions, and authentication use the existing settings of the same web app. The default execution services are ARTEX and PostgreSQL.

## actual execution loop

### Preparation and execution sequence

1. Prepare the **original vulnerability** saved as an existing ARTEX check. Review the reproduction range, inspection constraints, expected detections, etc. in **Defense Verification** of the vulnerability details and save the defense plan. Inherited vulnerabilities run from the source.
2. **Closed-loop → Select scenarios and vulnerabilities in the actual execution loop**. Check saved defense plan revision, vulnerability basis version and fingerprint. If you modified your plan from another screen, select **Read Latest Plan**.
3. Select **Splunk** or **Log File** as the log basis method. Splunk selects the registered search connection and prepares the file with the source name and field names of time, validation ID, action, and event ID. The log destination is inferred from the licensed assets of the original vulnerability, using `/` if the path prefix is ​​left empty. If the target values ​​recorded in the log are different, check the range settings.
4. Enter the baseline rule JSON. `equals` · `contains`, OR `any`, AND `all` are used, and if the saved defense plan is `event_filter`, the contents are loaded. The condition uses only the Allowed Actions fields from the original audit log. Execution UUID, time, event ID, and answer label are not used as detection conditions.
5. Confirm the target and privilege set and select **Actual Run Baseline Attack**. The ARTEX revalidation agent in an existing LLM setup sends the actual request and stores the revalidation ID, defense execution ID, and unique verification UUID. You can check or abort running sessions and status. Completion of execution and reproduction of vulnerability exploitation are separate judgments.
6. After execution finishes, wait **at least 60 seconds of log observation period**. Splunk retrieves audits and alerts with **real log collection and shadow evaluation**. The file uploads the audit file and alarm file of the corresponding execution and checks the viewing period and whether to export the entire file. If the actual alert query was empty, this will be stated in the file submission. Save actual log evaluation after upload. 60 seconds is the minimum wait and does not guarantee the maximum delay in schedule alerts and log reflection. If late alerts are possible, re-collect the same run and upload the files by re-exporting the original with the same hit range.
7. Select **Suggested Candidates from Baseline Audit Logs** or write your own candidate JSON. The proposal only uses stored baseline audit events and does not change the operating rules. Review the conditions and the possibility of normal activity, write down the **reason for the rule change**, and save the candidate revision.
8. Select **Rerun attack with new verification ID**. Run a new ARTEX revalidation with the same vulnerabilities and saved scan conditions. Collect logs again for the new UUID and new time range. Files from previous attacks are not used as evidence for new executions.
9. Check the actual alert before and after results and rule comparison basis and save them as **Export original evidence JSON**. One loop is fixed with a baseline attack and a pair of new reruns. After a rerun is made, create a new loop to modify the candidates or launch additional attacks.

We also maintain the **Breach Investigation** entry point for vulnerability details. Collecting actual execution logs and investigating AI past logs are separate tasks, and AI investigation does not automatically start with just the collection button.

### Two log sources

| Source | Gather evidence | Limits to check |
|---|---|---|
| Splunk direct query | Reads audits/alerts using stored connection·index·sourcetype and actual execution UUID·time range and applies two rules for audit search with limited target/path. | There is a difference between completion of the search and completeness of the sensor's collection coverage. Changes in connection settings and collection errors, limits or omissions remain the basis for comparison. |
| Upload File | Reuse audit/alert JSONL·JSON·CSV uploads from existing defense verification. The server verifies the source text, hash, execution UUID, and period and applies rules to the audit event. | Verification of origin and full export relies on the uploader's declaration. Local file matching does not prove that an alert occurred in the actual SIEM. |

The default mapping for the target/path/action fields is the source fields `target`, `path`, and `action`. There is `log_mapping` in the API, but currently the actual loop screen sets the default validation fields and destination/path range for the file. If your organization's source field structure is different, accept the defaults and don't consider this a complete collection.

### Differences between actual alerts and candidate rule matches

| screen result | Meaning | What it doesn't mean |
|---|---|---|
| Detection and blocking of actual existing alarms | Detection/policy action decision based on audit log and actual alert records of the execution | Evidence that a candidate rule has been installed, blocking confirmed by HTTP status code alone |
| Actual alerts attributed to a candidate rule | `detected` only when a new alert collected directly from Splunk includes the rule ID and its SHA-256 matches the saved candidate hash | A file reference alone does not prove independent attribution; missing attribution does not prove a missed detection or deployment failure |
| rule shadow evaluation | Match/disagreement/judgment is not possible by separately calculating standard/candidate conditions for actual audit logs | Actual alarm ignition or security policy change |
| Compare existing alerts from two runs | Alarm results observed in the baseline and new runs, respectively | Experiment with automatic control of changes to external rules and collection settings |
| Compare two rules from the same redo log | Results of applying baseline and candidate rules to the same audit event in a new run | Accuracy comparison of different input samples |

If the actual alert contains rule ID·SHA-256, its reference is shown separately. `candidate_native_rule_detection` is distinguished from the existing alarm results of the entire detector. If there is no explicit rule reference to associate with a candidate hash, `not_attributed`, we do not attribute the alert to a candidate just because the alert exists. If the collection range is incomplete, fields are missing, or values ​​are truncated, the results will remain unverifiable and will not be confirmed as false/successful.

Executing two attacks alone does not produce precision, recall, false positive rate, MTTD, or MTTR. Currently, real-world loops do not have normal traffic sampling, independent alert visual verification, or time basis for actual response execution. We do not show that number as a performance indicator of the actual loop.

### API and history preservation

The actual loop is saved in `/api/closed-loop/live-cycles`. Authentication is the same as in traditional web apps.

| request | Action |
|---|---|
| `GET /api/closed-loop/live-cycles` | Recent Real Loop List |
| `POST /api/closed-loop/live-cycles` | Run the baseline ARTEX and create a loop. `request_id` UUID, vulnerability ID, defense plan/basis version, log source and standard rules required |
| `GET /api/closed-loop/live-cycles/{id}` | Execution status, rules, observation summary, comparison conditions |
| `POST /api/closed-loop/live-cycles/{id}/collect` | View actual logs of terminated runs or evaluate uploaded rationale |
| `POST /api/closed-loop/live-cycles/{id}/suggest` | Candidate suggestions from saved criteria audit logs |
| `PUT /api/closed-loop/live-cycles/{id}/candidate` | Save candidates as `expected_revision`, `rule`, `note` |
| `POST /api/closed-loop/live-cycles/{id}/rerun` | Start of new physical revalidation for `expected_revision` |
| `POST /api/closed-loop/live-cycles/{id}/stop` | Stop current attack execution and preserve history |
| `GET /api/closed-loop/live-cycles/{id}/export` | Original log·execution snapshot·rule·hash·observation history JSON |

Sending the same UUID in the create request again will return the same execution. A re-execution request of the same revision also returns a new existing execution. If the expected revision is different, save/run is refused. If execution becomes stale due to a change in plan, basis, or log connection, re-execution or satisfaction of comparison conditions is limited, so check the changes and start in a new loop. For general detailed responses, the original text is omitted and the entire rationale is preserved for export. When making your original export public, remove authentication information and sensitive logs.

### Rule deployment scope

The Candidate Store, Collect, and Rerun API for a regular HTTP revalidation loop **does not automatically apply rules or blocking policies from your production SIEM.** Splunk connections use existing search accounts. The optional [local lab helper](../lab/purple/loop_rule.py), which separately checks for actual candidate alert firings, only covers dedicated saved searches in Splunk's separately owned lab. The optional [AWS Windows Bridge](aws-windows-loop.md) provides separate fixed practice targets and a separate route for actual application of standard/candidate rules for dedicated saved searches. The administrative rights for both lab paths are separate from regular product search connections and are not a universal deployment feature that changes existing operating rules or CRS.

## independent case investigation

1. In **Defensive**, enter the target host, start/end query, and path if necessary.
2. Select **File** to upload JSONL, JSON, or CSV logs, or select an existing search connection and sourcetype from **Splunk**. Splunk search preview only shows queries and does not run remote searches.
3. If the actual source fields are different, modify the field mapping. Confirmation items for log source, time, and target range are selected only when the original search conditions are confirmed.
4. Save the evidence to create a case. Log content, file SHA-256, search scope, collection warnings and static request flows are preserved. Vulnerabilities can be optionally linked and do not automatically create new vulnerabilities.
5. Select **Start AI Investigation** on a saved case if necessary. An existing LLM setup is required, and a portion of the selected logs will be passed to the appropriate model provider. File inspection has no logs outside of the uploaded file. Splunk investigations allow for additional read-only queries within existing tolerances.
6. In the investigation history, check plans, tool implementation, citing evidence, observations/inferences, normal alternatives, and requests for additional data. Stopped executions are also preserved. Original archiving uses a JSON export of an incident or AI run.

AI investigations are limited to a maximum of 3 plans, 18 model calls, 12 queries, 3 remote queries, and 4 minutes. Only one existing vulnerability investigation and one independent incident investigation can be run at the same time. After restarting the service, the remaining execution will be `interrupted` and will not automatically recall the model. Completion of an investigation is not the same as confirmation of infringement.

### Composite example of checking the screen without connection

[`incident.jsonl`](examples/aegisloop/incident.jsonl) is a **synthetic log**, not a practice log collected from the original system. You can upload the target `demo.example`, period `2026-10-09T09:00:00Z`~`2026-10-09T11:00:00Z`, and no path restrictions to save the file and check the timeline. UI time input is browser local time. It is 18:00~20:00 in Korean time. It is not possible to determine actual infringement based on the alarm/allow/block records in the example.

## Log Rule Evaluation: Traditional Offline Comparison

**Closed-loop → Log rule evaluation** maintains the existing upload/candidate proposal/indicator calculation/history/export flow. Executes the conditions `equals`·`contains` for `fields` in the input event. `any` is OR, and `all` in each branch is AND. This tab does not launch attacks, nor does it function as a Sigma·Suricata launcher or operational policy deployment function.

1. Name your scenario and enter your baseline rule JSON.
2. **Upload logs for improvement**. Each event must contain `event_id`, the correct answer `label` (`attack` or `benign`), and the actual observed field `fields`.
3. Candidate proposals only use logs for improvement. Verify that the proposed conditions are observable in the original logs and also match normal activity, and edit candidate rules.
4. After selecting candidates, upload a separate **evaluation log**. If the same event ID and same field contents are duplicated in the improvement/evaluation page, the evaluation will be rejected. label and event_id cannot be used as rule conditions.
5. Apply the criteria and candidate rules to the same evaluation log. Compare TP/FP/TN/FN, precision, recall, false-positive rate and event-specific evidence. Events with insufficient fields remain unknown, and if there is no denominator for the indicator, it is `null`.
6. When you save the evaluation history, the server recalculates the numbers and leaves them as an immutable record. Vulnerability/incident IDs can be selectively linked and the evidence at the time can be preserved together. Original logs, rules, SHA-256, and results are exported as JSON.
7. The remaining false positive, false positive, and missing fields are used as the next verification priority. You will not deploy candidates to Operations or run Offensive actions in this offline tab.

The MTTD of the sample is calculated only when there is actual alarm time `baseline_alert_at`·`candidate_alert_at`, occurrence time `occurred_at`, and time source confirmation for each rule. Undetected events are not included in the detection time average and must be read together with recall. We do not create an MTTR for this MVP as it has no actual response execution.

### Rule Comparison Synthesis Example

- For improvement: [`tuning.jsonl`](examples/aegisloop/tuning.jsonl)
- For evaluation: [`evaluation.jsonl`](examples/aegisloop/evaluation.jsonl)
- Base rule: [`baseline-rule.json`](examples/aegisloop/baseline-rule.json)
- Edited candidate rule: [`candidate-rule.json`](examples/aegisloop/candidate-rule.json)

The two datasets contain 2 attacks and 2 normal cases, respectively. The criteria is TP=1, FP=1, TN=1, FN=1 for evaluation since it only checks existing paths. Candidates check the private route and unauthenticated status together, so in this example TP=2, FP=0, TN=2, FN=0. These numbers are **values ​​to check that the matcher's calculations work on synthetic input** and do not prove practical detection performance. If `auth_state` is not in the actual log, this candidate cannot be used as is.

## Demonstration environment and follow-up scope

Juice Shop·WAF·Splunk·Attack Range and AWS targets are separate from the product's default installation configuration. **AWS is a temporary demonstration environment to see real-world behavior and create a public trail. Creating a long-term service infrastructure is not the goal of this project.** Preparing, operating, and cleaning up the environment is a separate hands-on procedure, and neither long-term maintenance nor the creation of additional cloud resources are prerequisites for actual loop functionality.

The reliability of the correct answer label and the original view depends on uploader verification. Field hashes cannot find all forms of duplicates, correlated samples, or label leaks. If the candidate is readjusted based on the evaluation results, the data is not final unused evaluation data and must be verified with new data.

We now offer independent investigation, offline evaluation, and a user-initiated real-world revalidation loop. Code/binary analysis adapter, fuzzer, ATT&CK coverage evaluation, Alert Triage dedicated agent, operational rule deployment approval, automation of actual response, and policy loop to autonomously change attack plan based on investigation results remain in [Follow-up Requirements](aegisloop-source-analysis.md#this-mvp-and-follow-up-requirements).
