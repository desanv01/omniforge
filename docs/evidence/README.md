# public practice testimonials

This directory holds **actual local usage screens** of ARTEX-based extensions. We checked vulnerability grounds, defense verification, prepared past log grounds, and AI investigation history against OWASP Juice Shop, which was run separately during development. Afterwards, we also confirmed actual detection, blocking, alarm deactivation, and ARTEX log collection in the optional WAF/Splunk lab environment.

**Juice Shop is not included in the product's installation configuration.** New users only need to run ARTEX and PostgreSQL following the [Basic Running Guide](../../README.md#quick-start). The vulnerabilities, practice logs, settings, and investigation history shown here are not automatically included in new installations.

## scope of evidence

- Screens are captured in a separate local lab environment and are not replaced with synthetic results or UI mockups.
- The detection and blocking results of defense verification are read together with the actual status and rationale limits displayed on the screen. The fact that a related path request has been detected is different from the success of blocking an attack or leaking data.
- AI investigations are executions that select stored logs and explicitly initiate them. The actual history disclosed is **user suspended or execution limit reached**, and is not presented as evidence of completion of autonomous investigation or successful confirmation of infringement.
- Initial Splunk connection and follow-up query regressions were verified with a mock HTTPS server. On 2026-10-10, we further verified the actual audit/alert search and ARTEX collection functions in a separate local Splunk. This is not evidence of a connection to the actual enterprise Splunk.
- Original log, DB, API key, JWT key, and connection authentication information are not included in the public records. Apart from the on-screen excerpts, the entire export file is kept locally only.

## screen

The current public screen is stored in the file below. The captions on each screen only describe what is actually visible in the capture.

### Diagnosis, defense verification, and infringement investigation conducted directly by the user

Seven actual captures are listed in order in the [User Guide](../USER_GUIDE_KO.md). Comparison of **detected/non-blocked → detected/blocked** between diagnostic task #4, vulnerability #5, and defense verification #2·#3, Splunk investigation basis, and record of reaching AI execution limit. We differentiate between log collection and defense decisions and AI investigation completion, and captured the saved records without new attacks or model calls.

### 2026-10-11 Latest integrated web screen

Display four screens directly on [README's actual web screen](../../README.md#screenshots). The file below is a capture of the running app with the menu visible, and is not a mock-up or composite image.

| screen | Capture | Verification range |
|---|---|---|
| Integration status | [Original Image](images/aegisloop-overview-2026-10-11.jpg) | Linkage of the three business areas and stored records. Card figures are record count, not detection performance |
| Offensive | [Original Image](images/aegisloop-offensive-2026-10-11.jpg) | Status of work, vulnerabilities, assets, and activities of existing ARTEX diagnostics |
| Defensive | [Original Image](images/aegisloop-defensive-2026-10-11.jpg) | Preparation form to start an independent incident with a file/Splunk log. Does not mean investigation is complete |
| Closed-loop | [Original Image](images/aegisloop-closed-loop-2026-10-11.jpg) | Before-and-after comparison of common samples and separate variant detection in actual AWS Windows and Splunk practice |

We didn't run any new attacks or model calls for the screen capture, we just used existing saved results and a blank ready-to-investigate form. The capture did not include API keys, credentials, or AWS addresses.

### Improved detection of AWS Windows scheduled task chains

![Web comparison of actual AWS chain attack, normal business, and modified attack](images/windows-task-chain-comparison-2026-10-11.jpg)

In fact, common attacks on AWS Windows and Splunk were detected both before and after improvement, and false positives in normal management tasks were reduced from **1 → 0**. A separate variant attack was also detected after improvement. These results are from a limited practice sample and do not imply an operational false positive rate. The verification scope is summarized in [Execution·Multiple logs·Rule application·Original export record](windows-task-chain-2026-10-11.md).

### Vulnerability Basis

![Vulnerability detail screen for separate local training](images/01-finding.png)

This is an unauthenticated information exposure vulnerability of `/ftp`, a separate local training target, `juice-shop:3000`. The revalidation record distinguishes between the incomplete response of `/ftp` and the response of `/ftp/acquisitions.md`. This screen connects the vulnerability/reproduction basis from which subsequent defense verification and breach investigation will begin.


### Defense verification using file evidence

![Detection and blocking judgment limits of audit/alert files](images/02-defense-validation.png)

The basis for the saved file is **2 audits and 2 alarms**, and the verdict is **evidence-based detection: detected / blocking confirmed by logs: no judgment**. The problem of not being able to interpret the block/allow action of one audit event is displayed along with instructions to check the actual policy action field. We do not indicate successful blocking simply because we have a history of detections.

The top of the screen is a new file submission form, with no file selected. The decision cards below are the results of already stored evidence. Full collection verification is also based on the uploader's declaration and is not the result of any independent verification of the original collection system.

### Breach investigation: Prepare your log evidence first

![Log basis preparation screen, the first step in infringement investigation](images/03-investigation-setup.png)

The screen guides you through the following steps: **Prepare log evidence → AI investigation → Check results**. Choose to upload a file or query Splunk directly, specify research questions, target hosts, paths, time ranges and mappings, and save your evidence. This capture is a preparation screen and does not indicate completion of file upload or AI investigation.

### Hypothesis and user stopping history of actual AI execution

![User stopped investigation and preserved hypothesis after model call](images/04-investigation-trace.png)

The actual execution history shows **2 model calls, 0 log views, and user stop**. The `/ftp`-related investigation hypothesis and goal set by the agent are preserved, but execution is stopped before the original log query is completed. Therefore, this screen shows **connecting models, creating plans, and keeping records after stopping**, and does not demonstrate completion of subsequent log analysis or discovery of traces of an attack.

The survey question also specified the scope of partial data exported with existing ARTEX revalidation UUID. Such materials and footage should not be construed as the result of an infringement investigation of any past activity.

### Real-world results from optional WAF/Splunk labs

![Screen summarizing audits and alarms from three practice cases in actual Splunk](images/06-purple-lab-splunk.jpg)

This is a screen showing the practice index searched using a search-only account in a local Splunk run separately. **Detection only: 3 audits, 2 alarms / Actual blocking: 3 audits, 2 alarms / Alarm inactive: 3 audits, 0 alarms**, for a total of 13 cases. One request for normal comparison of blocked cases was allowed, and the two scanned requests were linked to the WAF's actual blocking actions and Splunk alerts.

This screen is the result of an independent environment check command and does not show the completion of ARTEX AI diagnosis/re-verification. We distinguish between `/ftp` access protection policy and standard CRS's SQLi pattern check, and we have not confirmed successful exploitation of SQLi requests. The detailed scope is in [Actual Practice Verification Record](purple-lab-2026-10-10.md).

### Local Splunk connection registered with ARTEX

![ARTEX's local Purple practice Splunk connection and connection test screen](images/07-purple-lab-artex.jpg)

After the final app rebuild, it shows **local Purple lab Splunk** connected to ARTEX and **connection test successful**. The connection test is a communication/authentication verification of the hands-on Splunk management API, and this screen alone does not determine the success of audit/alert collection or detection. The actual collection was confirmed by reading 5, 5, and 3 of the three cases above by running a separate Go connector.

The new diagnostic target is `purple-lab-target:8080` in front of the WAF. The `juice-shop:3000` target and past results of existing vulnerability number 3 remain the same, and new ARTEX diagnosis and re-verification requires separate execution and a basis for such execution.

## Read verification separately

The latest environment preparations are summarized in [Real Web Practice/Splunk Incident Preparation](purple-lab-ready-2026-10-10.md), [Installation of Official Attack Range Management Service](attack-range-install-2026-10-10.md), [Verification of Settings Before AWS Construction](attack-range-aws-preparation-2026-10-10.md), [Local AWS Certification/Seoul Plan Verification](attack-range-aws-plan-2026-10-10.md), and [One Week Manually Operating AWS Construction](attack-range-aws-deployment-2026-10-11.md). The scope of verification of server creation, host log, detection, and product integration is differentiated in each record.

The execution and test results of the new source checkout and secret exclusion inspection are summarized in [Deployment Verification Records](validation-2026-10-09.md).

### New installation without developer data

![Initial password setup screen opened from new checkout](images/05-clean-install.png)

After re-cloning the distribution source to a separate folder, I ran only ARTEX and PostgreSQL. The existing key, environment file, and DB are not copied, and it starts from the initial password setting screen. In this verification installation, we did not set an administrator password or issue an LLM call.

| Materials | What to check | What is not proven |
|---|---|---|
| Source build/integration test | Execution control, scope constraints, parsing/evidence preservation, API contracts and regression | Real detection accuracy, operational SIEM compatibility with all LLM providers |
| Local screen in this directory | Actual screens for vulnerabilities and functions stored in separate practice targets | Occurrence or non-occurrence of corporate infringement, defensive effect of operating policy |
| History of actual AI investigation suspension | Record the start and progress of execution and keep the record after stopping | Investigation completed, auto accident confirmed |
| Optional WAF·Real local Splunk inspection | Actual actions/alerts in three cases, search-only account inquiry and ARTEX collection | ARTEX AI diagnosis completed, SQLi exploit successfully, detection accuracy in corporate environment |

Please refer to the [Source Distribution Guide](../release.md) for execution and test commands, and the [Defense Verification](../purple-validation.md) and [Infringement Investigation](../cert-investigation.md) documents for judgment and scope of investigation.
