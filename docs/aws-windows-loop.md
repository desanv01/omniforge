# AWS Windows Lab and Closed-loop Connection

The AWS lab environment is a separate environment to check **actual Windows behavior → log collection → detection rule improvement → alarm comparison of new execution**. We use an optional bridge at `/closed-loop/?tab=range` on the web to connect to your existing Windows/Splunk lab environment. The default installation using only ARTEX and PostgreSQL and the HTTP vulnerability re-verification and file evaluation functions are maintained.

This document describes the connection structure and implementation procedures. We verified the execution of three Atomic techniques on existing AWS Windows → Collect real Splunk alerts → Deploy candidate rules → New execution. The detection result of this exercise was **1/3 → 3/3**, and the scope and basis are summarized in [Actual Verification Record](evidence/aws-windows-loop-2026-10-11.md).

## Role of the two web screens

| screen | Use | Connection range |
|---|---|---|
| `/closed-loop/?tab=range` by AegisLoop | Running fixed Windows lab scenarios, deploying baseline and candidate rules, and comparing actual logs and alarms | Existing practice set up on a separate bridge Windows·Splunk |
| `http://localhost:4321` by Official Attack Range | Scope creation/status/simulation management of formal tools | Settings, cloud authentication, and connection preparation managed by the official API are required |

4321 The management screen and this bridge connection are separate. Terraform states created separately on the host are not automatically registered with the official API. Simulation of the official UI can only be used if the corresponding API's range settings, executable state, and target server are in place. To use AegisLoop's AWS Windows tab, you do not need to create a new range or connect cloud authentication to the official UI.

## Preparation and connection setup

The bridge connects only to Windows and Splunk that you already own and prepare. Windows requires Sysmon, Windows Audit/PowerShell log collection, Splunk Universal Forwarder, Atomic Red Team's execution modules, and the original test YAML. Confirmation of normal collection and confirmation of detection alarm ignition are differentiated on their own basis.

A separate bridge configuration holds static exercise target, connection method, original Atomic YAML hash, Splunk authentication, and dedicated rules information. Private settings and access keys are excluded from Git. Prepare Docker, the Attack Range API image you already have installed, and a private session directory from your existing deployment, then use the following public setup tool:

```sh
python3 lab/attack-range/bridge_setup.py --session /path/to/your/existing-session
./scripts/local-start.sh
```

The setup tool checks the ownership tags of the existing Terraform state and reads the three installed Atomic sources on Windows over a static SSH connection. Create private bridge configuration and Compose environment files by verifying the encrypted WinRM connection, Atomic GUID/command/original file hash, and Splunk certificate pin. If the existing certificate pin is different, it is not automatically replaced and the existing bridge token is reused. SSH tunnels that are used briefly to prepare for setup are cleaned up when setup is completed. This command does not launch atomic attacks or call AWS-generated APIs.

Optional [`docker-compose.range-bridge.yml`](../docker-compose.range-bridge.yml) connects:

- `ARTEX_RANGE_BRIDGE_URL` and `ARTEX_RANGE_BRIDGE_TOKEN_FILE` on the ARTEX server.
- Bridge's private configuration file/token file, fixed SSH access key/host confirmation data, and execution history storage folder.
- Bridge service inside Docker. No separate public ports, Docker sockets, or cloud creation APIs are used.

If `compose.env` with project-specific private bridge settings is ready, `scripts/local-start.sh` will read the optional Compose together. In a default installation with no settings, the AWS Windows connection status displays as unset and other features are available.

The browser logs into ARTEX and calls the static API. Bridge tokens are read from the file by the ARTEX server and used only for internal requests. Don't include your AWS profile, administrative credentials, SSH keys, or Splunk passwords in the browser response. Merely showing a connection status as Ready does not verify successful execution or detection of a particular test.

## Recommended: PowerShell → Scheduled Tasks → Delayed Execution

In actual AWS verification, normal sample false positives were reduced from **1 → 0** while maintaining common attack detection, and a separate variant attack was also detected. You can check the sample range and basis in [Web screen and actual verification record](evidence/windows-task-chain-2026-10-11.md).

On the web, select **PowerShell → Scheduled Tasks → Delayed Execution** Bundle. This bundle runs separately from existing Atomic navigation scenarios and runs on a single copy of Windows. No new AWS servers are required.

| steps | Running sample | Results to check |
|---|---|---|
| Baseline Execution | 1 attack chain + 1 normal management task | Broad PowerShell Rules for Attack Detection and Normal Business False Positives |
| Evidence review | Real Windows Audit + Real Splunk Scheduled Scan Alerts | Connection between command execution, task registration, and delayed execution, causes of false positives |
| Rules Improvements | Review and distribution of fixed behavior correlation profiles | Change from regular PowerShell execution to correlation criteria for suspicious activity behavior |
| Improvement Redo | Same type of attack/normal operation + separate modified attack | Before and after comparison of two common samples and deformation detection results |

Execution schedules a one-time task to write a harmless results file. Check the actual task end code/result file hash and organize the task and result directories. No logs are created and injected. Transformations use different paths and execution arguments and are executed first after application of candidate rules. This is a predefined separate verification case and does not imply generalization performance for all unknown attacks.

Detection rules do not use test UUID, task name, or private file name as conditions. We concatenate the actual PowerShell command with the task name, Windows task registration, the scheduler's execution PID, and the Sysmon process rationale. Identifiers are used only for attribution to the evaluation object. Candidates for improvement are reviewable **fixed detection profiles** and not random rules automatically generated by LLM.

### log preparation

Adds the following to the existing Sysmon 1·11, Security, and PowerShell 4104 log collection:

- TaskScheduler Operational channel and Splunk delivery.
- Other Object Access Events Success Audit: Scheduled Task Registration 4698.
- ScheduledTasks module logging 4103: Associating the task name of the actual `Register-ScheduledTask` with the PowerShell process that ran it.
- Sysmon 11 collection of JSON files generated by PowerShell: This is for comparing execution results with separate audit logs, and applies equally to attacks and normal operations.

First check the AWS connection status on the web to prepare the bridge tunnel, then run the following command in the local project folder. If the bridge container name is different, use that name.

```sh
docker exec -i artex-local-range-bridge-1 python - --apply < lab/attack-range/prepare_chain_telemetry.py
```

If you leave out `--apply`, only the settings will be searched. The staging tool preserves existing audit/module logging settings and Sysmon XML in `C:\AegisLoop\telemetry`. After checking the path/SHA-256 of the active Sysmon settings, add the JSON file collection condition to a new XML retaining the existing filter and prepare a separate Splunk input app. Restarts the SplunkForwarder service on Windows when adding input for the first time. This setting will remain available for future use of web verification as well. We do not retroactively generate missing logs from runs that have already ended, so after you have supplemented your collection settings, you start a new baseline run.

If Sysmon in other environments collects FileCreate as an exclusion condition only, the tool will stop adding inclusion filters to narrow the existing collection. Existing exclusion conditions take precedence, so the success of the prepare command alone does not confirm file audit collection. You should check out Sysmon 11 in action on a step-by-step basis on the web.

### Proceeds after detection on the web

1. Enter a run name and select a recommended chain to start a baseline run.
2. After the run is complete, click **Collect Actual Windows Logs/Splunk Alerts**. Waiting for reservation search reflection and collection are performed asynchronously.
3. Check the judgment for each attack/normal sample, actual basis for each step, timeline, and cause analysis. Alerts in normal operation are false positives, not successful attack detections.
4. **Tap a candidate proposal in the criteria log** and review the proposal rationale and behavioral profile. Write down the reason for the change and **Save candidate and apply to practice Splunk**.
5. After applying is complete, start a new rerun. Real-world execution of common attacks, normal operations and new variant attacks.
6. Collect logs/alerts again and compare TP/FN/FP/TN of common samples in **Before and After Improvement**. Transformation attacks are identified as a separate item.
7. Download the original supporting JSON or reopen the same record, including the `cycle` value in the resulting URL. The new Ready for Verification button allows you to start the next verification.

Execution failures, missing logs, and lack of correlation are **unable to determine**. Normal No Alarm (TN) or Attack No Detection (FN) is calculated only when execution and log coverage and actual scheduled scan completion are confirmed. The number shown is for this practice sample and does not estimate the operational false positive rate based on a single normal sample. Alarm delay is the difference between the original behavior and the actual alarm creation time, and includes a search delay of 1 minute.

## Existing Atomic Exploration Scenarios

Existing Labs We'll use the following tests from the original Atomic YAML on Windows as our anchoring scenario: Verifies equality based on GUID and original file SHA-256 rather than numerical order.

| Scenario | ATT&CK technique | Fixed Atomic GUID | act |
|---|---|---|---|
| Current user navigation | T1033 | `aab580c7-cc30-4a7c-b5a9-46a29066b022` | User verification via `whoami` |
| Explore running processes | T1057 | `c5806a4f-62b8-4900-980b-c7ec004e9908` | Check running process with `tasklist` |
| Explore system information | T1082 | `66703791-c902-4560-8770-42b8a91f7667` | `systeminfo` and disk related registry search |

It is not the ability to type arbitrary commands, other targets, or batch execute entire techniques on the web. If the original file or execution premise changes, verification using the existing fixed settings is not considered. Test selection is an actual execution request on an authorized practice subject, not just a screen preview.

## Order of progress on the web

1. Check the bridge connection status and fixed targets/scenarios in the **Closed-loop → AWS Windows tab**.
2. We start the baseline loop by selecting which of the three fixed scenarios to run. The bridge only executes the selected source Atomic and saves the baseline rules and task state. If the request is in the task received state, the progress of the loop is checked and the same attack is not started repeatedly.
3. Wait for execution to finish and log reflection to collect actual evidence. View alerts separately from Windows execution results, raw Sysmon events, and Splunk search results of that scope.
4. Propose candidate rules based on audit logs from baseline runs or edit conditions for allowed observation fields. Consider what omissions you are trying to compensate for and whether they can also be consistent with normal behavior.
5. Save the candidate rule. In this lab path, you will apply actual candidate rules to **practice Splunk's dedicated saved search** pinned by the bridge. Stores rule content, SHA-256, remote rule identifier, and application results.
6. Starts a new physical rerun. Retain the original scenario and targets and record the new execution identifier, time, and process rationale. Logs from previous runs are not submitted as new run results.
7. Re-collect actual audit events and alerts from the new run. Check the remote alarm rationale for the baseline and candidate rules, respectively. Simple condition matching results and actual alarms are not displayed with the same judgment.
8. Export and store pre- and post-execution records and original supporting JSON. Failures, missing collections, and unclear correlations are also left behind.

The Task Completed screen indicates that the request has been processed. The exit code of the actual execution, whether or not the original log is collected, the result of applying the rule, and the occurrence of an alarm for the rule are separate items to be checked.

## Criteria for linking real evidence

The key audit basis for Windows loops is the **ProcessGuid** of the actual Sysmon process creation event. The bridge connects the execution target, time, and command with the actual process basis and separates baseline execution and re-execution. We do not create new attack launches by writing random IDs to a file or re-reading existing verification events.

Security 4688 and PowerShell 4104 do not assume that Sysmon's ProcessGuid is the same in all Windows logs, although this can be verified by additional logs collected. Do not forcefully attribute logs without fields or correlations to the same process.

Determining that a candidate actually raised an alert requires a remote rule identifier/rule SHA-256 and a **native Splunk alarm basis** that is associated with the new execution. The fact that the audit log matches a rule or triggers an alarm in another existing rule does not confirm a candidate's alarm is fired. Search failures, collection delays, missing coverage, or lack of correlation should be left as unconfirmed or failed.

The hash of the original file, search result, rule, and execution basis is a value to confirm the source of the history. Hashes alone do not prove log completeness or detection success. We do not create actual measurement values ​​such as precision, false positive rate, or MTTD without a correct sample of normal traffic or independent visual evidence.

## Management authority and scope of operation

Lab Splunk's ability to change rules is limited to the private settings of the optional bridge. Keep the existing ARTEX's regular Splunk search connection read-only. This bridge is not an interface to deploy arbitrary SPLs or freely change operating rules and response policies in a corporate SIEM.

This integration uses existing lab resources and does not create new AWS resources or IAM permissions. Maintenance and termination of existing AWS resources are managed by the practice owner as a separate procedure. Simply connecting a bridge or terminating a local container does not delete AWS resources.

Because the original export may contain sensitive Windows logs, public traces are stripped of target identifying information, personal information, and authentication information. Public repositories do not contain actual administrative settings, access keys, original private logs, or operational databases.

## Fixed API

The following path uses ARTEX's existing login authentication. The bridge connection address and authentication token are not specified by the requestor.

| request | Action |
|---|---|
| `GET /api/closed-loop/range/status` | Bridge settings/readiness status |
| `GET /api/closed-loop/range/cycles` | Lab Loop History |
| `POST /api/closed-loop/range/cycles` | Baseline loop reception of selected fixed scenario |
| `GET /api/closed-loop/range/cycles/{uuid}` | Execution/Task/Collection Status |
| `POST /api/closed-loop/range/cycles/{uuid}/collect` | Collect actual logs/alarms of the execution |
| `POST /api/closed-loop/range/cycles/{uuid}/suggest` | Proposal of candidates on the basis of baseline audit |
| `POST /api/closed-loop/range/cycles/{uuid}/candidate` | Save limited candidate rules and apply practice |
| `POST /api/closed-loop/range/cycles/{uuid}/rerun` | New Actual Redo Filed |
| `GET /api/closed-loop/range/cycles/{uuid}/export` | Export original evidence and history |

If there is no setting, the status query returns `configured:false`, `ready:false`, and the execution request is rejected. ID only accepts UUID and does not carry additional query conditions or free paths. Requests and general responses are allowed within 1 MiB, and original JSON export responses are allowed up to 64 MiB. We do not forward redirects, authentication information, or browser cookies to other services. Asynchronous operations are confirmed through reception results and subsequent status inquiries.
