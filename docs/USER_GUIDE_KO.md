# AegisLoop User Guide

AegisLoop connects ARTEX-based vulnerability diagnosis with detection/blocking verification and log-based breach investigation.

The capture below is a saved screen of the Juice Shop·WAF·Splunk exercise conducted by the user. We used diagnostic task #4, vulnerability #5, defense verification #2·#3 and the corresponding log investigation records. The number of screens varies depending on the installation environment.

```text
진단 → 취약점 확인 → 탐지·차단 확인 → 방어 개선 → 재검증·비교
로그 준비 → AI 침해 조사 → 근거와 후속 조치 확인
```

## 1. Getting started

Run the app according to the [Installation instructions](local-development.md) and log in with the account you initially set up. Set up model connections in **System → LLM**.

| screen | Use |
| --- | --- |
| Offensive → Action | Run diagnostics and check vulnerabilities |
| Vulnerability details → Defense verification | Comparison of reproduction/detection/blocking results before and after improvement |
| Defensive → Log Connection | Register a Splunk connection |
| Defensive → Alert/infringement investigation | Investigate incidents with files or Splunk logs |

You can use the separately prepared **Juice Shop + WAF + Splunk** environment for practice. Complete [Installation of Lab Environment](purple-lab.md) first. The lab environment is not included in the default installation of the product.

## 2. Diagnose vulnerabilities

1. Open **Offensive → Tasks → New Task**.
2. Enter the authorized target address and inspection scope in Description and Goal and press **Create**.
3. Once the diagnosis is complete, check the results and evidence for reproducibility in the **Vulnerability List**.

Example local lab input:

```text
대상: http://purple-lab-target:8080
목표: 무인증으로 /ftp/acquisitions.md에 접근 가능한지 확인하고,
재현 요청과 관측 결과를 근거로 접근통제 취약점을 기록한다.
```

This address is the WAF front end address used by the ARTEX container. When opening the lab target in your browser, use `http://localhost:18790`.

**Actual diagnosis results:** Access control vulnerabilities were recorded based on the `200 OK` response of unauthenticated file access. The detailed screen below also displays the subsequent re-verification history. The `수정됨` on the screen is a follow-up revalidation status and is not proof of a code modification.

![Directly diagnosed file access control vulnerabilities and re-verification history](evidence/images/user-guide-finding.jpg)

<details>
<summary>View completion status and PoC of original diagnostic tasks</summary>

![Diagnostic task completed and recorded request/response PoC](evidence/images/user-guide-diagnosis.jpg)

The request/response PoC is recorded on the screen. Separately linked traffic evidence is displayed as 0.

</details>

## 3. Check detection and blocking

1. In the vulnerability details, under **Defense Verification**, fill in the detection hypothesis and log source and click **Save Plan**.
2. Select a log connection method.
   - **Splunk:** Select the registered connection.
   - **File:** Prepare audit and alarm logs appropriate for the verification ID and execution section.
3. Press **Start ARTEX Diagnostics + Defense Verification**.
4. After the diagnosis is complete, Splunk waits at least 60 seconds and clicks **View Splunk logs/alarms**. The file method uploads logs to that run.
5. **Reproducible judgment**, **Evidence-based detection**, and **Block confirmed by logs**. If the log reflection is delayed, it will be viewed again.

The request may be allowed even if detected. HTTP status codes alone do not confirm actual blocking.

**Actual results before improvements:** Vulnerability reproduced, detected, not blocked. One audit log and one alert were collected from Splunk.

![Splunk rationale before improvements — requests detected but not blocked](evidence/images/user-guide-defense-before.jpg)

## 4. Re-verify after improving defense

After applying the WAF policy or detection rule to the actual system, the same vulnerabilities are re-verified. **Just writing improvement actions into your app does not apply the policy.**

In my local lab, I can change the WAF mode in the terminal in my project folder. Each change is made after running diagnostics and log collection.

When preparing for a pre-improvement run:

```sh
./scripts/purple-lab.sh mode detection
./scripts/purple-lab.sh alerts on
```

After saving the pre-improvement results and preparing to run the post-improvement results:

```sh
./scripts/purple-lab.sh mode blocking
```

1. Select **Run baseline before improvement** and write **Improvement actions applied**.
2. Start a new revalidation with the same plan/log connection and also collect logs for that run.
3. Check the comparison conditions and results in **Comparison before and after improvement**.

Examples confirmed in `/ftp` access control practice:

| Item | Before improvement | After improvement |
| --- | --- | --- |
| Vulnerability reproduction | Reproduced | Not reproduced |
| detection | Detected | Detected |
| Block | Not blocked | blocked |

This comparison shows the effectiveness of the WAF blocking policy and does not imply modifications to application code or improvements in detection accuracy.

![Comparison of actual defense verification — detection remains and changes from unblocked to blocked](evidence/images/user-guide-defense-comparison.jpg)

<details>
<summary>View reproduction judgment and Splunk evidence after improvement</summary>

![Not reproduced after improvement, detected, blocked judgment and applied WAF actions](evidence/images/user-guide-defense-after.jpg)

</details>

## 5. Investigate breaches with logs

Even if there are no vulnerabilities, you can start from **Defensive → Alert/Breach Investigation → Start New Incident**.

1. Select **Upload file** or **View Splunk directly**.
2. Enter target, period, path and research questions and map source log fields.
3. For files, **prepare and save file basis**, and for Splunk, **preview Splunk search conditions → search and save Splunk basis**.
4. Check your saved events and timeline, then press **Start AI Investigation**.
5. Review observed behavior, assumptions linking evidence, missing data, and subsequent research.

The local lab enters `purple-lab-target:8080` in Target, `/ftp` in Path, and the actual diagnostic time in Period. The target field mapping is `target`.

Example research question: “Explain when file access was allowed and blocked in conjunction with alerts, and distinguish between ARTEX verification requests and other requests.”

If there are 0 logs, check the target/period/field mapping first. The scope of a saved investigation is fixed, so if you want to change the scope, prepare the basis with a new incident. For AI research, selected log excerpts are sent to the LLM you set up.

**Actual Inspection Record:** At the time, we looked up the property without narrowing down the path. Of the 891 stored events, 4 were identified as known ARTEX verifications, and the remaining 887 were not confirmed attacks. Collection coverage was incomplete, and AI research reached implementation limits and remained incomplete.

![Incomplete indication of research basis and collection scope collected by Splunk](evidence/images/user-guide-investigation-evidence.jpg)

<details>
<summary>View the current AI survey execution status — Incomplete</summary>

![Actual investigation record of reaching the execution limit after 5 model calls and 7 log views](evidence/images/user-guide-investigation-limit.jpg)

Log collection/basic analysis and AI investigation completion are separate. This capture is a record of the execution at the time and does not evidence the completion of a later revised version of the investigation.

</details>

## Check and store results

- **Unable to make a decision:** There is insufficient evidence to make a decision. Just because there are no logs doesn't mean you should conclude it's safe.
- **Execution limit reached:** AI investigation is incomplete. Check saved partial results and unconfirmed items.
- Archive results with comparison screen/timeline and **JSON export**. Data to be disclosed excludes authentication information and sensitive original logs.

Details: [Defense Verification](purple-validation.md) · [Breach Investigation](cert-investigation.md) · [Full Features and Limitations](aegisloop.md)
