# ARTEX diagnostics and actual defense verification

Re-check vulnerabilities found with the existing ARTEX revalidation agent, and link audit logs and actual alarms with the same execution UUID through file upload or Splunk query. Based on the evidence collected, detection and blocking are judged separately, distinguishing between identified problems and causes for further inspection, and comparing performance after applying improvement actions.

| method | Basis and meaning |
| --- | --- |
| File upload verification | Connects ARTEX re-verification with user-uploaded audit logs and alarms. Export scope depends on user's confirmation |
| Splunk query validation | Connect audit logs and alarms retrieved from Splunk linked to ARTEX re-verification |
| Manual verification records | Preserve the results and evidence of human observations and input |
| log replay | Evaluate whether the uploaded log matches the stored event conditions |

File uploads and Splunk queries use the same execution and evaluation functions and indicate the source. Manual recording and log playback are separate histories and tallies. It does not record LLM's diagnostic conclusions, manual entries, or log replay passes by turning them into actual alarms. ARTEX revalidation requires LLM setup and an authorized target, while manual recording and log replay can be used without an LLM key.

## Try it first: Upload a file

1. In the vulnerability details, under **Defense Verification**, save the plan and select **File Upload** as the connection method. You don't need a Splunk account.
2. Specify the log source name and field name. The default fields are Time `timestamp`, Execution UUID `artex_verification_id`, Actual Action `action`, Event ID `id`. Dotted nested fields are also supported. Sources and field settings are preserved at their runtime values.
3. ARTEX re-verification begins. Prepare log collection settings so that the execution UUID of the screen is transmitted to the header of the actual reproduction request and the target audit log/alarm. The original diagnostic target and task constraints apply.
4. Export and upload audit logs and alarms up to 60 seconds after the end of execution. Supports UTF-8 JSON array, JSONL, and CSV. Audit log is required and if there is no alert file, select it only if you **confirm that there are no alerts in the scope of the query**.
5. The exported period must include from 30 seconds before the start of the run to 60 seconds after the end. Up to 24 hours, no time in the future can be specified. Make sure you include all audit and alarm details for that period. Unconfirmed states can also be analyzed, but they are not determined as undetected and remain undetermined.
6. Check detection/blocking results, identified issues, additional causes to check, and recommended actions. Uploading a modified file in the same run will add new verdicts rather than overwriting previous rationales.

This is an example application format. The values ​​below are for illustrative purposes only, do not upload instead of actual logs, use the actual records in your log export.

```json
[{"id":"실제 이벤트 ID","timestamp":"2026-10-09T09:00:00+09:00","artex_verification_id":"화면의 실행 UUID","action":"allowed"}]
```

Alert files must be **actual detection alerts** with the same time/UUID fields. `action` is used when evaluating blocks in the audit log and recognizes `blocked`/`block`/`denied`/`deny`, `allowed`/`allow`/`passed`/`pass`. Missing action fields indicate blocking decisions as impossible. If an event ID is not found, an identifier is calculated from file basis. Plain text, compressed files, and images are not supported.

The two original files total up to 4 MiB, for a total of 5,000 events, with one event up to 128 KiB. If this input limit is exceeded, the upload will be rejected. The evaluation target is up to 200 events each for audit and alarm, and if this limit is exceeded, it is judged as incomplete basis. Displays the count, excluding other execution UUIDs and out-of-range events, and incorrect formatting or missing required fields will indicate errors or inability to determine.

Saves file name, SHA-256, original text, field settings and input range. The screen preview excludes the original text, and the full JSON export includes the original text. File content is parsed locally and is not sent to an external LLM by this function. It does not open server paths or URLs or execute commands written in files.

### How to read the cause of detection failure

- **Facts found:** Mismatched execution UUID, missing fields, insufficient collection scope, no audit log, no alerts for that execution, allowable actions logged in audit log, etc. Check with file, line or event basis.
- **Additional causes to check:** Disabled detection rules, mismatched conditions/fields, missing alert delivery, etc. We do not confirm one or the other just because there are no alerts. Check and re-verify the actual rule/collector settings.
- **Unable to determine:** There are insufficient logs or the scope has not been confirmed. Distinguish it from a conclusion that the attack was not detected.

File-based decisions are based on user-provided records and scope checks. The product is not the result of independent verification of the authenticity of complete logs or files from the source system.

## 1. Existing Splunk connection

Directly connect the search account you already use in **Defense Validation → Splunk Log Connection**. ARTEX does not create Splunk accounts or indexes.

| Entry | value to set |
| --- | --- |
| Splunk Management API Address | HTTPS address for the existing management API. Do not attach path/account/query |
| index | One existing index to search for audit logs and alerts |
| Audit log sourcetype | Audit log source for actual target request |
| alert sourcetype | The source of the alert that the deployed detection rule actually raised. Must be different value from audit log |
| Verification ID field | Field to read execution UUID from both logs. Default `artex_verification_id` |
| Block/Allow result field | Actual Control Results field in the audit log. Example: `action` to `blocked` or `allowed` |
| Authentication method | Username/password for an existing search account or an existing Bearer token |
| Certificate SHA-256 Fingerprint | If you are using a private certificate, the exact fingerprint of the trusted server certificate |

Currently, the connector supports **different audit and alert sourcetypes** for the same index. The connected account needs Search API permissions for its logs. **Connection test** only verifies communication and authentication of the server information API, so even if it succeeds, it does not confirm the collection of target logs or occurrence of alarms.

Save and activate the connection. Authentication information is encrypted with a key derived from ARTEX's JWT key and stored in the DB, and is not included in inquiry/export responses. In local configuration, `.local-runtime/jwt.key` must be preserved with the DB. If you lose or replace your key, you will need to re-enter your saved credentials. Re-enter your authentication information when you change the connection address.

## 2. Pass execution UUID to requests and logs

When you start running, the server generates a UUID and passes it to the revalidation agent as a `X-ARTEX-Verification-ID` header. Agents are instructed to attach this value **only to HTTP requests that actually reproduce the vulnerability on the original, authorized target. Login, session preparation, and normal verification requests are checked separately in the existing revalidation flow without attaching this UUID. The original authentication status, request conditions, and operation constraints are maintained.

The following connections must be prepared in the log settings of the target service or front-end device.

1. Retain request header values ​​in `artex_verification_id` in the audit log. If you use a different field name, specify that name in the **Validation ID field** of the connection.
2. Leave the actual action `blocked` or `allowed` in the audit log and map it to the **Block/Allow result field**. Blocking is not determined solely based on status codes such as HTTP 403.
3. When a deployed detection rule generates an alarm, **the same UUID is preserved in that alarm** and collected into the specified alarm sourcetype. It does not replicate audit logs as alerts or assume detections just because a UUID is present.

ARTEX does not automatically change the target's log settings, collectors, or detection rules. Header delivery instructions are not proof of success, and non-HTTP diagnostics or requests for which headers cannot be delivered will remain inadmissible without a correlating basis.

## 3. Run in Splunk and collect evidence

1. Open the vulnerability in the **Defense Verification** list and go to the **Defense Verification** tab in Details.
2. Save detection hypotheses, logs to check and defensive actions to the plan. Saved rule drafts are not automatically deployed to your SIEM or executed as search statements.
3. Select an active Splunk connection and press **Start ARTEX Diagnostics + Defense Verification**. The existing ARTEX revalidation agent will run and you can open a diagnostic dialog in its history.
4. When the diagnosis is complete, wait **60 seconds after completion** and press the log/alarm collection button. Status refresh only checks diagnostic progress, and SIEM evidence is collected at the push of a button.
5. Check detection and blocking decisions, inquiry sections, number of audits and alerts, and next actions. If logs come in late, they are collected again in the same run. Adds new rolls without overwriting previous rolls.

The inquiry section is from 30 seconds before the start of diagnosis to 60 seconds after the end. If you collect it early, it will only look up to the current time and mark it as incomplete. 60 seconds is a fixed observation interval and does not guarantee log delivery completion. If the alert itself is generated later than this interval, it will not be included in the current execution's view scope.

| Judgment | Required Evidence |
| --- | --- |
| Detected | Normally completed re-verification, sufficient inquiry section, audit log with same UUID and actual alarm |
| undetected | In the above conditions, there is an audit log, but there is no alarm with the same UUID |
| blocked | Explicitly block all actions in the evaluable audit log |
| Not blocked | Explicitly allow all actions in evaluable audit logs |
| No judgment (`inconclusive`) | Execution failure/interruption, no audit log, incomplete query, time/UUID mismatch, missing/mixed actions, etc. |

Even if detected, it may not be blocked. If there is no action field or if block and allow are mixed, the blocking side remains undetermined even if the detection result is confirmed. `재현됨·수정됨·판단 불가` stored by LLM is **Vulnerability Diagnosis Conclusion** and is separate from the above judgment. Once the existing revalidation is completed as modified, the vulnerability status may change as per existing behavior, but the SIEM decision is made separately based on the collected evidence.

Inquiry processes up to 24 hours and up to 200 audit and alarm events each. Exceeded limits or search warnings will be marked as incomplete. Connection/inquiry failures are not saved as detection success or blocking success.

## 4. Compare and export before and after improvement

After diagnosing and gathering evidence for pre-improvement execution, the target's defense measures or detection rules are applied. Select **Run baseline before improvements** on the same vulnerability and start a new run by writing down the description of the improvements you applied. The UUIDs for the two runs are different.

To compare, the baseline run must finish first, both diagnostics must be completed normally, and the latest detection/blocking judgments for each must not be undecidable. The original target asset/vulnerability type/operation constraints, evidence source, and configuration version must also be the same. Post-remediation implementation should be consistent with current plans, vulnerability evidence, and source settings. If the conditions are insufficient, the reason will be indicated and the improvement effect will not be confirmed.

Execution saves a copy of the original diagnosis, targets/constraints, defense plan and source settings at the time. If the plan, vulnerability basis, target address, IP, task constraints, or connection settings change, past records are kept and excluded from current performance tally. Past runs with changed source settings cannot be further collected, so a new run is started with the current settings. `현재 버전` means that the version of the record matches and does not mean that the defense was successful.

The screen and comparison results pre-display 30 recent executions, 5 recent judgments for each execution, and 20 events for each judgment, and exclude the original upload text. Counts and decisions are based on the entire collection basis. **JSON export** includes a copy of the original diagnostics of the selected run, plan/source settings, revalidation conclusions, all verdicts and archived files, or the original Splunk results. Does not include source authentication information. New collections are added as new histories and there is no ability to modify individual judgments. A before-and-after comparison of the file method must also have the same source names and field settings, and does not confirm the effectiveness comparison between the file method and the Splunk method.

Job storage and restoration also includes execution and judgment history. If there is a defense revalidation in progress, it must be terminated first to archive the work. Deleting a vulnerability also deletes the associated plan and verification history.

## Manual recording and log playback

For manual recording, you write down the observation time, log/alarm ID, etc. and select the detection/blocking results separately. If only one side is confirmed, the other side is left unconfirmed. It is not combined with an aggregate of actual SIEM collection results.

Log replay is executed by saving the rule format of the plan as **event condition (JSON)** and then inputting the detection target log and normal comparison log. The input is an array of JSON objects, or JSONL, and processes up to 1 MiB and 2,000 events in total. The input original text is stored in the local DB for reproduction purposes and is not sent to an external LLM.

```json
{"version":1,"all":[{"field":"access.cross_owner","op":"eq","value":true}]}
```

A match occurs if up to 16 `all` conditions are met. `eq`·`neq` compares the same types of strings, numbers, and Boolean, and `contains` checks whether strings are included. Field names with dots use the same top-level key first; otherwise, nested paths are read. Search queries, Sigma, and other formats are kept as drafts and will not be executed by this engine.

To pass, both inputs must exist, all target events match, and all normal events must mismatch. Missing or false positives are failures, and if there is any empty input, insufficient field, or type mismatch, judgment cannot be made. The screen previews the 50 most recent executions and 50 event details, and the export includes the full text, conditions, results, and SHA-256 hash. These results are a conditional evaluation of upload logs and are not evidence of actual SIEM detection or blocking.

## API and development testing

Uses existing ARTEX certification. The execution/source/vulnerability ID is a JSON string, and the existing revalidation ID is a number.

| path | Use |
| --- | --- |
| `GET/POST /api/purple/sources` | View and save existing Splunk connections |
| `PUT /api/purple/sources/{sourceID}` | Fix connection, check `expected_revision` |
| `POST /api/purple/sources/{sourceID}/test` | Management API communication/authentication confirmation |
| `GET/PUT /api/exploration/findings/{id}/defense` | Defense plan/manual history inquiry and plan saving |
| `GET/POST /api/exploration/findings/{id}/defense/executions` | Start execution history inquiry and re-verification of existing ARTEX |
| `POST /api/exploration/findings/{id}/defense/executions/{executionID}/collect` | Add real Splunk queries and new verdicts |
| `POST /api/exploration/findings/{id}/defense/executions/{executionID}/upload` | Upload audit/alert files, connect evidence and check cause |
| `GET /api/exploration/findings/{id}/defense/executions/{executionID}/export` | Full rationale for selected execution JSON |
| `GET /api/exploration/findings/{id}/defense/executions/compare?baseline_id=…&current_id=…` | Comparison of execution before and after explicitly linked improvements |
| `POST /api/exploration/findings/{id}/defense/validations` | Add manual records |
| `GET/POST /api/exploration/findings/{id}/defense/replays` | View and evaluate log playback history |
| `GET /api/exploration/findings/{id}/defense/replays/{runID}/export` | Playback input/rule/result JSON |
| `GET /api/purple/overview?page=1&limit=20` | Aggregation by method and status by vulnerability |

The run generation checks `source_kind` (`file` or `splunk`), `plan_revision`, `expected_evidence_version`, and `expected_source_fingerprint`. The file method uses `source_id:"0"` and `file_config`, and the Splunk method uses the existing `source_id`. The omission of `source_kind` from older clients is interpreted by Splunk. For file upload, pass `audit_file:{name,content}`, optionally `alert_file`, `no_alerts`, `coverage_start`, `coverage_end`, `coverage_complete`. The enhancement run adds `baseline_id` and `remediation_note`. If there is an active revalidation, no new executions are started redundantly.

`./scripts/local-test.sh` in [Local Development Guide](local-development.md) checks the behavior with separate ad-hoc PostgreSQL and HTTP responses for testing. Passing an automated test does not mean that the diagnosis, detection, or blocking has been verified on a real target. Actual results are confirmed by execution and collected history in the user-connected environment.
