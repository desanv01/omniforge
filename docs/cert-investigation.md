# Vulnerability-based breach investigation

In the **Breach Investigation** of the vulnerability details, prepare historical logs by **file upload** or **Splunk direct query**, press **Start AI Investigation**, and the ARTEX agent will iterate the investigation plan and follow-up queries based on the evidence. It does not run new vulnerability checks and can be used even if there are no ARTEX validation UUIDs in past logs.

The existing [Defense Verification](purple-validation.md) checks whether the re-verification performed now has been detected and blocked. Breach investigations look for relevant activity in existing records for selected assets/periods. Because the file formats and lookup scopes of the two features are different, do not examine the entire past activity solely from files exported by the UUID Filter for Defense Validation.

## Preparing evidence and investigating agents

Select an Information Exposure, Authentication, Code Execution, SSRF, or General Investigation template based on the vulnerability name, classification, and description. For each hypothesis, it provides conditions for validation, necessary logs/fields, search methods, normal behavior alternatives, and next actions.

The plan on the first screen is a **conditional survey template** managed by code. An LLM connection is not required for file parsing, Splunk initial viewing, basic analysis and storage. Keep your survey questions in your records and use them as base questions for future AI surveys.

**ARTEX Agent Breach Investigation**, launched separately from stored grounds, reuses the existing `agentcore` execution base of ARTEX and the currently active LLM connection. Planners determine hypotheses/tasks based on vulnerabilities and investigation questions, workers check evidence with a dedicated log query tool, and planners receive observation results and decide whether to follow up or stop the investigation. We do not provide shell, attack, or web access tools for general penetration inspection.

Planners and operators first check stored incident names/questions, actual event types/actions/path distributions, field mappings, and up to eight normalized samples. Operators are provided with up to three full-text excerpts (1,200 bytes each) and their supporting references are included in the progress history. Observations are recorded from logs already obtained, and recorded observations and unconfirmed items are preserved even when the time limit is reached. The entire investigation may not be completed in time due to slow models or additional queries.

Conflicts between Splunk's `source` metadata and fields with the same name inside JSON can result in different strings being returned as arrays. In this case, individual events/original text are preserved without randomly selecting one, and events with ambiguous origins are excluded from the request flow connection of the same origin. Please note that source verification warnings and incompleteness remain. Ambiguous values ​​in investigation scope fields such as target, time, and route will continue to be strictly rejected.

Automated rules from fundamental analysis address asset/path access and limited multi-path request flows. Subsequent hypotheses such as use of exposed credentials, account takeover, server process execution, server egress, etc. lead to additional evidence needed. AI investigation can review additional connections in the obtained logs, but does not create non-existent authentication, host, or transmission logs or automatically confirm infringement.

## Common investigation scope

1. Open **Investigation of Breach** from the vulnerability details.
2. Enter your investigation title and questions, and choose how you want to connect your logs.
3. Specify **target host or host:port**, optional path, and past start/end time of the source log.
4. Match the field mapping to the original log and then analyze it according to the connection method below.

In the target field, enter a host like `juice-shop:3000`. The event's target value can be a host or HTTP(S) URL. The hosts must match exactly, and if you specify a port, that port must also match. Default ports omitted in HTTP and HTTPS URLs are interpreted as 80 and 443, respectively.

`/ftp` path includes below `/ftp` and `/ftp/`, but does not include `/ftp-backup`. If you leave the path empty or specify it as `/`, the entire asset path will be examined, and you will need to check separately whether each event is related to a vulnerability. Enter the time in your screen's local time, including the start time but excluding the end time. Past logs that are not preserved will not be restored.

**AI research is also searched only within the first saved target, time, and path.** For example, if you want to access `/ftp` and then check the request for `/login` for the same asset, clear the path before collecting evidence and prepare a log containing both paths. In an investigation that has already been limited to `/ftp`, the agent does not expand the scope to `/login` on its own. If other assets, periods, or log sources are needed, separate evidence for a new scope is prepared.

## file upload

1. Select **Upload File** and enter a log source name.
2. Select the UTF-8 JSON·JSONL·CSV file needed for the same investigation.
3. Map **time, target, and path** first. The default fields are `timestamp`, `target`, `path`. Session, departure point, event type, etc. are added according to the data.
4. Check **Check full export** only if you have confirmed that all relevant results for the target, path, and period have been exported from the source system.
5. To include rows without target fields, verify that the file was actually exported from that asset and then check **Confirm that rows without target host fields were also collected from the above target**.
6. Press **Prepare/Save File Basis**.

The two confirmations have different meanings. If there is no full export confirmation, the collection will be marked as blank. Target validation applies only to rows without a target field, not including rows where a different target is specified. User verification does not imply independent verification of the original collection system.

JSON supports single object, array of objects, and JSONL, and the first row of CSV must be a field name without duplicates. Time uses RFC 3339 or Unix seconds. The field name is the name of the actual value; dotted fields can also be used, such as `request.path`. If there is a direct field with the same name, it takes precedence over the nested object. Like the Splunk export, if you have a JSON object string in `_raw`, it will look for values ​​in it that are not at the top level.

If you analyze audits and alarms together, map the event type to `event_kind`, etc. so that the alarm rows are divided into `alert` or `경보`. Alerts are flagged as observations, but do not count towards the request count for multi-request flows. The UUID field is optional, and its absence does not exclude regular past events.

## Splunk direct query

1. Select **Splunk Direct Query**. If there is no connection, **Connection Management** saves the existing Splunk HTTPS management address and search account or token.
2. Select the active connection where your authentication information is stored. Your account must have search permissions on the index you want to query. ARTEX does not create accounts, indexes, or detection rules.
3. Select the sourcetype you want to investigate. The default value is the audit/alarm sourcetype stored in the connection, and up to 8 can be specified.
4. Map fields such as destination and path that match the source. Splunk surveys use **`_time`**, which is the search time reference.
5. Check the automatically created search expression and range with **Splunk query condition preview**. Preview does not run remote searches.
6. Click **View/Save Splunk Evidence**.

The query is limited to one stored index and the selected sourcetype, destination, time, and optional path. There is no function for users to enter and execute arbitrary SPL commands. Treat target values ​​as exact host conditions and paths as literal boundary conditions. Does not require validation UUID as a search condition.

Use HTTPS certificate validation or a saved certificate pin and do not send authentication information following a redirect. Reuse encrypted credentials from an existing connection. In a Docker environment, the Splunk management API must be reachable from an ARTEX container.

Splunk errors are not saved as success results. Warnings, previews, missing completion marks, and exceeding event limits are treated as results in the entire collection being unconfirmable. You can also store 0 searches that end successfully, but this does not verify the original log retention period or collector coverage.

The destination field in the local Purple lab log is `target`. Splunk's `host` is the collector name, so we don't use `purple-lab-target:8080` as a search target condition. When switching to Splunk, only the default time/event IDs are changed to `_time`·`_cd`, while retaining target fields and user-modified mappings. If the number of stored evidence is 0, a guide to confirm the target field, period, path, and source type is displayed in front of the AI ​​investigation. Incorrectly saved conditions must be corrected by preparing a new basis, and the saved range will not change even if only the AI ​​is re-run in the same event.

## Run AI research

1. Save the log evidence to a file or Splunk and open **ARTEX Agent Breach Investigation**.
2. Check your research question and saved scope. If LLM is not connected, enable the connection you want to use in **System → LLM Settings**.
3. Tap **Start AI Survey**. We don't call the model just by saving the rationale or opening the page.
4. On the progress screen, check hypotheses, research tasks, inquiries, observations citing evidence, and follow-up decisions. Stop execution if necessary.
5. Compare the supporting references of the results with the original text, review data deficiencies and follow-up research. **Running a new AI survey** creates a separate history and new model usage.

The planner presents one research task at a time. Workers search using structured target, time, route, origin IP, account, session, and event type conditions, read the original text of important events, and leave observations. The planner determines the next task based on the results. The progress on the screen shows tasks, tool use, and explicit investigative decisions; it does not show the model's internal thought processes.

In file mode, only saved events are searched. You cannot access past activity that is not on file or in other log systems. In Splunk mode, you can query stored events or search further with the same connection, index, sourcetype, and mapping. Each additional search rechecks whether the connection is active and has changed, and the target, period, and path can only be narrowed from the initial scope. Since the search expression is generated by the server, the model does not run arbitrary SPLs. If custom sourcetype scopes are not preserved in existing records or their associations have changed, new evidence collection is required.

AI investigations transmit a portion of the vulnerability description/evidence, investigation questions, selected log fields, and text excerpts to **the established LLM provider** and may incur usage/fees for that connection. The entire uploaded file is preserved in the local DB and is not put in its entirety in the prompt. Splunk connection credentials are not passed to the model, but sensitive values ​​such as accounts, sessions, and tokens contained in the log itself may remain in the excerpt, so use data that can be transmitted.

### What AI Results Mean

| display | Meaning |
|---|---|
| `observed` | AI interpretation of events viewed by agents and read the original text. We verify the existence of citations and do not guarantee the accuracy of interpretation or success of infringement |
| `inferred` | A hypothesis that connects the evidence read. Record other explanations such as normal behavior |
| `insufficient_data` | Required logs, fields, and ranges are lacking. Additional information or next research item |

Observations can only cite supporting references confirmed by actual inquiries, and `observed` must be read in the original text first to be saved. If known ARTEX reproduction requests are included, these are marked separately. Evidence verification is intended to prevent event identifiers created by AI, and does not mean that the same IP can be viewed as the same attacker or that HTTP 200 can be interpreted as a successful leak.

| running status | Meaning |
|---|---|
| `queued` / `running` | Waiting to start / Investigating |
| `completed` | Planner completes research work. Not a confirmed infringement or safety determination |
| `insufficient_data` | Terminated due to lack of sufficient evidence |
| `budget_exhausted` | Exhaustion of execution budget such as rounds, calls, tokens, time, etc. |
| `cancelled` | Execution stopped by user |
| `model_error` | Ended with model call error. If you have saved observations, keep them together |
| `interrupted` | Interruption due to service restart/termination or result preservation issues |

Saved progress and evidence remain until cancellation, failure, or restart. Does not automatically resume terminated runs or overwrite results. To investigate again, the user starts a new run. You run one AI investigation on one server, and jobs with running investigations can be archived after the investigation ends.

## Read fundamental analysis results

| display | Meaning |
|---|---|
| `observed` | Actually observing relevant path events in that range |
| `suspicious` | Observe the request flow that requires confirmation. Attacker/exploit success not confirmed |
| `not_observed` | No such pattern was observed in the identified survey range. This does not mean there was no infringement |
| `insufficient_data` | Unable to evaluate sufficiently due to gaps in collection scope, fields, parsing, etc. |
| `manual_review` | The evidence and conditions required for subsequent hypotheses must be additionally verified by humans |

Multi-path analysis of information exposure looks for two or more different sub-paths within 10 minutes of the same log source, destination, or session (or origin, if none exist). By distinguishing file, sourcetype, source, host, and index, records from different sources are not merged into the same request flow. We do not determine that they are the same attacker just because they have the same IP, and normal resource loading or shared IP are also suggested as possible explanations.

HTTP 200·403, allow/block values, and path access alone do not determine success in file transfer, account hijacking, code execution, or blocking. Investigating the actual scope of delivery requires additional data, including bytes transmitted, completed responses, and file contents at the time.

Known ARTEX verification requests are distinguished when the UUID registered for the same vulnerability and the actual revalidation time range match together. The range is from 30 seconds before revalidation starts to 60 seconds after it ends, excluding the end boundary. Leave the event in the timeline and exclude it from the suspect flow. Unknown UUIDs or UUIDs that are out of time are not automatically excluded. Since the header mark is not a means of authentication, it must be compared with the original request and inspection schedule.

## Basis/History and Export

Each evidence collection and AI execution is stored as a separate record. Examining a new file or different range creates a new history without overwriting previous results. AI execution does not change the original file or underlying analysis. If the vulnerability basis changes, existing records will show that they are the result of the previous basis, and new AI executions will require the log basis to be re-prepared based on the latest vulnerability. The evidence history and the AI ​​execution history of the evidence each display the most recent 30 cases, and previous originals are also kept.

**Evidence JSON export** includes the current status of vulnerability, investigation plan, and connection settings, field mapping, inquiry section, collection warning, event text, file name, line, and basis reference, file hash, and text. Splunk also preserves the actual search expression and the text of the returned export. Authentication information is not exported. A hash identifies the preserved bytes and is not a signature that guarantees the authenticity of the original system.

Logs are preserved in the local DB. The entire original text of the file is excluded from the general history/detailed response and included in the explicit export. The original text of the selected event is used to check detailed evidence. After obtaining the necessary additional data, investigate again, or separately apply detection and defense measures appropriate for the identified behavior and verify the effectiveness by verifying the existing defenses.

**Export AI investigation history** saves the original investigation basis along with the settings, usage, progress events, and AI results of that run. Splunk's subsequent query conditions, return text, file hashes, and supporting references are also preserved in progress events. The same original text is referenced in the results without being stored redundantly, and the results and basis of the terminated execution are separated from subsequent executions.

## Current limits and development structure

| Item | limit |
|---|---|
| One survey period | Past section up to 31 days |
| Number of uploaded files | 1~20 |
| Upload original text total | 8 MiB |
| Number of input events | 10,000 |
| 1 event | 128 KiB |
| Related events to include in analysis | 2,000; If exceeded, mark as incomplete collection |
| request flow showing | 50; Additional investigation information when exceeded |
| Splunk sourcetype | Up to 8, index 1 of the saved connection |
| Splunk response body | 4 MiB; If exceeded, return as query failure |
| Splunk original artifact | The export body and event JSONL are preserved together and are less than 8 MiB in total |

Splunk Search requests the 10,001st row to check for exceeding the limit, and if it does, it does not mark the entire collection. In large surveys, the search is conducted by narrowing down the period and route. When the number of related events exceeds 2,000, even if additional lines remain in the original text, those lines are not automatically displayed as analyzed.

AI execution is additionally subject to the following fixed caps:

| Item | limit |
|---|---|
| Repeat planning and research | Up to 3 times |
| model call | Up to 18 times |
| Call log inquiry tool | Up to 12 times, of which up to 3 additional remote Splunk views |
| Running time | Up to 4 minutes |
| upper model response bound | Up to 2,048 tokens per call; If the active LLM has a smaller setting, apply that value |
| Conservative Token Reservation Budget | 180,000 units |
| Delivery of search results | Up to 20 at a time, subsequent pages can be confirmed with additional views |
| Read original text | Up to 5 excerpts at a time, up to 4,096 bytes per event |
| AI observation record | Up to 24 |
| Save progress/additional evidence | Server stops collecting more at about 20 MiB in total; DB settings, events, and final results total upper limit 24 MiB |

The token reservation budget is a conservative calculation limited by adding the number of UTF-8 bytes of the serialized request + the response token cap + margin before each call. 180,000 is not the actual number of billing tokens or the provider's token per minute limit. Actual provider usage is recorded separately, and connection speed limits, authentication, and rate settings are still applied. When the time, storage, and inquiry limits are reached, the obtained evidence and remaining investigation items are preserved and terminated.

- [Basic Research Engine](../investigation/): Conditional planning, common parsing, range filters, timeline and request flow analysis.
- [Agent Execution](../agent/investigator.go), [Dedicated Tool](../agent/investigator_tools.go), [Call Budget](../agent/investigator_provider.go): Planning, investigation, re-planning and ground-reference verification using existing execution base.
- [Splunk Query](../securitysource/investigation.go): Created read-only search, collect actual responses, verify completion/limits.
- [Investigation API](../server/investigations.go) and [Storage Layer](../db/investigations.go): Authentication, vulnerability/connection change checking, original text preservation, history/export.
- [Execution API](../server/investigation_runs.go) and [Execution Storage](../db/investigation_runs.go): explicit start/stop, asynchronous execution, additional basis preservation, restart recovery, history/export.
- [Local Execution·Test](local-development.md): Use of test DB and mockup Splunk server separated from actual operational data.

This version is an evidence-based investigative aid. AI suggests hypotheses and follow-up investigations, but automatic isolation/blocking, random SPL execution, restoration of facts not in logs, and automatic confirmation of infringement from authentication/host logs are not included in the scope of implementation. Mock models/DB tests isolated from Splunk verify execution control and evidence preservation and do not instead prove the success or detection accuracy of actual provider calls.
