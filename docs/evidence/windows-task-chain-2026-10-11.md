# Windows Scheduled Task Chain Verification History — 2026-10-11

By connecting existing AWS Windows and practice Splunk to AegisLoop web's **Closed-loop → AWS Windows practice**, we reviewed the actual basis of attacks and normal activities and confirmed the flow of improving detection rules. This record is a trace of the PowerShell → Scheduled Task Registration → Delayed Execution chain.

**Common attacks were detected both before and after improvement, and normal business false positives were reduced from 1 to 0. A separate modified attack was also detected.** Actual log and Splunk alarm collection was completed for both baseline and post-improvement execution, and there were no samples that could not be judged. These are the results of the limited practice sample below.

![Results before and after actual improvement found on the web](images/windows-task-chain-comparison-2026-10-11.jpg)

![Actual step-by-step logs and judgment basis for transformation attacks](images/windows-task-chain-evidence-2026-10-11.jpg)

The two screens were captured by reopening the saved actual verification records on the web on 2026-10-11. The first screen shows before-and-after comparison of common samples and separate variant determination, and the second shows the basis for the variant's PowerShell, task registration, delayed execution, and result organization. The attack was not re-run to capture it.

## Environment and validation samples

- We used existing practice Windows, Splunk Universal Forwarder, practice Splunk and optional execution bridge. For this chain verification, no new AWS server or IAM permissions were created.
- The web runs a fixed chain bundle `ps_task_chain`. It is executed separately from the existing atomic search scenario, and there is no arbitrary command or arbitrary target input function.
- Common samples from the baseline run include one attack chain `chain_attack` and one normal management task `chain_benign`.
- The improved re-run runs two new common samples of the same type and adds one separate variant attack, `chain_variant`. Transformations are predefined verification cases that use different task paths, script names, and execution arguments.
- The task creates a harmless results file. Check execution results, file hash, task completion code, and task/result directory organization.

Only logs from the baseline run are used for candidate proposals. The transformation attack is executed first after applying the candidate, and does not mix the variant samples with the before and after indicators of the common sample.

## Link to real evidence

| basis | Checking connection |
|---|---|
| Sysmon 1 | The actual PowerShell startup process and ProcessGuid |
| PowerShell 4104·4103 | PID of starting process, script block, actual `Register-ScheduledTask` job name parameters |
| Security 4698 | Registration of the task and TaskContent executable file, arguments, and work directory |
| TaskScheduler 129·200·201 | Delayed execution PID of the same task, action start and normal completion |
| Sysmon 1·11 | Generate the ProcessGuid and actual result file of the subsequent process corresponding to the execution PID |
| Hands-on Splunk Alerts | Remote Rule ID · Rule SHA-256 · ProcessGuid · Native Alert whose source time matches the corresponding execution |

The rule runs as an actual Splunk scheduled search and collects the `logevent` alert. Also check the normal completion/execution time range and input limit of the reservation search. It does not calculate an attack detection or a normal no-alarm simply because the search results are empty. Missing logs, execution failures, lack of object connection, and conflicting ProcessGuids are left as **unable to determine**.

Execution UUID, task name, and dedicated file name are used only to link the basis of the test. It is not included in the conditions of the detection rule. Baseline execution and improvement re-execution use different execution ID, time, and actual process rationale.

## Collection supplementation and transfer decisions are not possible

In the initial test, even though the execution results were confirmed, the chain judgment could not be confirmed because the Sysmon 11 basis in the result file was missing. The existing Sysmon filter did not collect PowerShell's JSON result file creation, and there were differences in file associations because the short path in Windows was different from the long path in the original log.

After the next supplement, **implementation of the new standard** began.

- I verified the path and SHA-256 of the active Sysmon configuration and preserved the original XML. PowerShell's JSON file creation collection condition was added to the existing XML. This is an audit collection condition that applies equally to attack and normal operations.
- The execution working directory and resulting file path were normalized to a long Windows path and connected to the actual file creation log.
- Prepared TaskScheduler channel/delivery input, successful audit of scheduled task registration, and logging of the ScheduledTasks module. Previous audit/module settings and input settings were preserved.

Complementation does not retroactively generate missing logs for executions that have already completed. Previous inconclusive runs are excluded from the sample of confirmed criteria results below. Allows late original recollection of the same execution, but does not automatically rerun the attack.

## Confirmed before and after results

The confirmed reference cycle is `a64f7748-131c-400f-a0d8-85e4b3438d3d`. This record does not include target IP, account, hostname, or management authentication information.

| Common Specimens | Actual Verdict of Baseline Rules | Improvement Rerun Judgment |
|---|---|---|
| 1 attack chain | TP: See real native alerts | TP: Check candidate rule alert for new process |
| 1 normal maintenance task | FP: Real alarms occur even during normal activities | TN: Actual Normal Execution·Collection Complete·No Candidate Alerts |
| Common sample indicators | **TP=1, FN=0, FP=1, TN=0, Unable to determine=0** | **TP=1, FN=0, FP=0, TN=1, Unable to determine=0** |

A separate variant, `chain_variant`, was identified with **1 TP** in the new run. After improvement, when all three samples are combined, TP = 2, FN = 0, FP = 0, TN = 1, but the transformations were not added in the before and after comparison of the common sample.

Baseline rule `powershell_broad` widely detected PowerShell process execution. The attack chain was detected, but normal operations were also classified as alerts. After verifying the original correlation basis and collection completeness of the baseline implementation, these false positives were used as a basis for improvement.

## Candidate application and new verification

After reviewing the basis of the baseline log and recording the reason for the change, the `task_behavior` profile was actually applied to Splunk practice. Candidate application completed revision is **2**.

Candidates change from simple PowerShell execution to multiple log correlation conditions of task registration, suspicious execution parameters, writable working directory, and actual delayed execution. Proposal explanations, review records, and rules/remote application grounds are preserved in the history. If the reference log is incomplete or the common sample cannot be determined, candidates cannot be applied even through direct API requests.

The new rerun took place from 2026-10-11 09:59:10 to 10:00:31 KST. All three tasks confirmed exit code 0, independent result file hash, actual log connection, and scheduled task/result directory cleanup. The final collection was completed after a 150 second alert observation interval.

| Basis for collection | standards | After improvement |
|---|---|---|
| Run ID | `338a5cb7-33c3-4346-83c3-e0bcbf415cff` | `9b3928c0-1330-4331-acf8-88db5d08ac7e` |
| Correlation audit basis displayed on the web | 24 cases | 36 cases |
| Actual alarms attributed to that run | 4 cases: 2 attack, 2 normal | 2 cases: 1 attack, 1 variant, 0 normal |
| Collection Scope | complete, no warnings | complete, no warnings |
| Decision not possible | 0 cases | 0 cases |

The number of alerts above is different from the number of sample judgments. The baseline rule raised an alert to the start and subsequent PowerShells in the chain, and the candidate alerted the correlated follow-up process. This includes attributing the actual rule ID, SHA-256, and ProcessGuid, completing the reservation search, and checking the limit on the number of entries.

Execute baseline on the web → Collect alerts → Save candidate suggestions and change reasons → Apply Splunk for practice → Rerun new → Collect alerts → Compare before and after. The resulting URL is `/closed-loop/?tab=range&cycle=a64f7748-131c-400f-a0d8-85e4b3438d3d`, and it opens the same record even after refreshing.

I downloaded the `aegis.range.native.v1` file using **Export JSON** on the web and checked the completed status and the original basis for both executions. This export is 43,126,159 bytes and has SHA-256 `462939c5f61f801e08afc95dcaa382bcce092a713eeace3e724b8e1f13884634`. The original file is kept private, and only the above screen capture and summary are included in the public repository.

## Verification scope and limitations

Candidates for improvement are **Fixed Detection Profiles** that can be reviewed. It does not demonstrate the results of LLM's creation of arbitrary detection rules or the universal rule deployment capabilities of an enterprise SIEM. This management permission is limited to the separate practice Splunk and dedicated rules set on the optional bridge.

Since there is only one common normal sample, the false positive rate, precision, and accuracy of the entire corporate environment are not estimated. We do not claim generalization performance for all unknown attacks as a result of predefined variant cases. Although alert delays are recorded, they are individual observations, including scheduled retrieval and collection delays in one-minute intervals, and are distinct from the average response time of multiple independent runs.

Local mock executor, original judgment, 27 bridge flow regression tests, web TypeScript, Biome inspection, and static build passed. Passing this test and actual AWS execution results are separate grounds. Original Windows logs, task XML, and execution receipts are stored as private exports. Management credentials are not included in both exports and public repositories.

For execution procedures, refer to [AWS Windows Practice Guide](../aws-windows-loop.md), and for verification of previous search techniques, refer to [Actual Verification Records of Three Atomic Techniques](aws-windows-loop-2026-10-11.md).
