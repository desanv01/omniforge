# WAF/Splunk defense verification practice

An optional hands-on environment to run a local vulnerability assessment with ARTEX and see if the same request is blocked by a WAF and detected by Splunk. Run Juice Shop, ModSecurity·OWASP CRS, log collector, and Splunk as separate Docker Compose projects. The product's primary implementations remain ARTEX and PostgreSQL.

## connection structure

```text
ARTEX → purple-lab-target:8080 → WAF → Juice Shop
                                  ↓ 실제 검사·조치 로그
                              로그 수집기 → Splunk
                                              ↓ 실제 탐지 규칙 결과
                                      ARTEX 방어 검증
```

The WAF address is also used when connecting to the target in the browser. Juice Shop direct addresses cannot be used for WAF blocking verification. WAF inspection results and actual request processing records are collected as audit logs, and the results of Splunk detection rules are collected as separate alarm logs. The initial WAF mode is `DetectionOnly` and must be changed to `blocking` to verify actual blocking. HTTP status code or verification UUID itself is not used as a basis for detection or blocking.

| Connection target | default address | Use |
| --- | --- | --- |
| ARTEX | <http://localhost:8787> | Diagnosis/Defense Verification/Breach Investigation |
| Juice Shop in front of WAF | <http://localhost:18790> | View lab targets in your browser |
| Splunk Web | <http://localhost:18000> | Check collection logs and detection rule results |
| Diagnostic targets for ARTEX containers | `http://purple-lab-target:8080` | Diagnosis and re-verification through WAF |
| Splunk management API in ARTEX containers | `https://purple-lab-splunk:8089` | Read-only log query |

The externally exposed web port connects to `127.0.0.1` on the local computer. ARTEX connects to the lab Docker network `artex-purple-lab-front` to access the above alias. Do not use `localhost:18790` or `localhost:18000` as a diagnosis/search address in the ARTEX container.

## Welcome to the lab environment

Requires Docker Desktop or Docker Engine, Compose v2, and Python 3 on the host. Splunk containers have a memory upper limit of 4 GiB, and since they also run Juice Shop, WAF, and ARTEX, allocate enough memory to Docker. Start ARTEX first, then run the following command from the repository root:

```sh
./scripts/local-start.sh
./scripts/purple-lab.sh init
./scripts/purple-lab.sh start --accept-splunk-terms
./scripts/purple-lab.sh status
```

The `--accept-splunk-terms` in the command is an explicit choice to agree to the [Splunk General Terms](https://www.splunk.com/en_us/legal/splunk-general-terms.html) and the image's license terms. Use only if you confirm and agree to the terms and conditions. `init` only prepares local folders and authentication information and does not accept terms or run containers. Once you have recorded your consent, you can start over with just `start`.

The first run may take some time due to downloading the image and initial configuration of Splunk. On Apple Silicon, Splunk's `linux/amd64` image runs in emulation. After checking readiness, proceed to the next step.

The default trial for Splunk Enterprise is 60 days. Because Splunk Free does not have alerting and user/role capabilities, the actual alerting and search-only account configuration for this lab requires a valid Enterprise Trial or a license that supports those features. Please refer to [Splunk Official License Guide](https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.6/configure-splunk-licenses/about-splunk-free).

The lab certification information and settings are stored in `.local-runtime/purple-lab/`, which is excluded from Git, and the exported evidence is stored in `evidence-local/purple-lab/`. Please do not post your password or token to GitHub. The index and search accounts created in the lab environment are used only for Splunk for this lab.

## First check the environment itself

2026-10-10 We verified three cases by running a real WAF and Splunk in a local environment. In each case, there are 3 audit logs, and the actual Splunk alarms are 2, 2, and 0, respectively, for a total of 13 cases. The same 5, 5, and 3 cases were read using ARTEX's Splunk collection function, and all searches were completed, with 0 warnings. We also passed 42 Python unit tests for Collector, TLS, and Splunk configurations. The screens and verification range are summarized in [Actual Practice Verification Record](evidence/purple-lab-2026-10-10.md).

```sh
./scripts/purple-lab.sh check

# Splunk를 제외하고 실행 중인 WAF와 감사 로그만 확인
./scripts/purple-lab.sh check --waf-only
```

The default `check` checks three cases: Detect/Not Block, Detect/Block, and Turn Off Alarm using actual requests and Splunk searches. After the scan is complete, restore WAF to `DetectionOnly` and Splunk alerts to `on`. `--waf-only` only checks the processing and audit logs of the already running WAF, restores the WAF to `DetectionOnly`, and does not start Splunk or agree to the terms and conditions.

Each check reads the byte count and SHA-256 from the frozen Juice Shop exercise file `acquisitions.md` from the target container and compares it to the actual HTTP response. The detection-only section checks whether the entire 909-byte file is delivered, and the blocking section checks whether the same file is not delivered and an explicit block is left in the WAF audit log. The original file body, account, and token are not printed. This confirmation only demonstrates successful access to an intentionally vulnerable local exercise file and does not imply a successful enterprise data leak or SQLi exploit. The current readiness status and actual verification results are compiled in [Environmental Readiness Record](evidence/purple-lab-ready-2026-10-10.md).

An example of turning off an alarm is voice verification to check whether the collection/judgment path is operating normally. It is not used as evaluation data for actual detection performance or rule improvement effectiveness. Performance verification requires collecting both actual missed behavior and normal activity with alerts turned on, changing rules, and verifying them with a new run.

The entire scan record is saved in `evidence-local/purple-lab/environment-check.json`, and the record of only WAF scans is saved in `evidence-local/purple-lab/waf-check.json`. This recording is an independent environmental check and does not create a vulnerability/defense verification run by ARTEX. **Do not upload the UUID and log generated by the verification command as the basis for another ARTEX re-verification.** The actual ARTEX execution is separately verified with the UUID generated in the corresponding screen.

Environment checks examine actual local requests passing through the WAF, audit log collection, and the results of Splunk rule execution. It does not complete ARTEX's LLM diagnostics on your behalf or generate vulnerability results. ARTEX diagnosis/re-verification requires an activated connection in **System → LLM Settings**.

There are two types of detection conditions in the lab.

- **Information Disclosure Path Protection:** Explicit practice policy for Juice Shop's `/ftp` and subpaths. This is used to compare before and after improvements that allow, detect, or block access to this path.
- **OWASP CRS Attack Inspection:** Checks request patterns, including SQL injections, that CRS identifies. In this detection-only check, the backend response to the SQLi request was HTTP 500, and the rule match does not demonstrate a successful SQLi exploit. The results of blocking CRS requests are not used as a basis for improving the `/ftp` information exposure vulnerability.

## Connect to ARTEX and run new diagnostics

```sh
./scripts/purple-lab.sh connect
```

`connect` targets a configuration where the default local ARTEX, `artex-local-artex-1`, is running on `http://127.0.0.1:8787`, and `.local-runtime/jwt.key` is preserved in the same checkout. Creates a short API authentication using an existing key in memory and does not reset passwords or print authentication information. Add a lab Splunk connection and a new WAF asset and prepare the ARTEX container for lab network access. It doesn't change the original target address of existing Splunk connections and existing vulnerabilities. The connection screen can be checked in **Defense Verification → Splunk Log Connection**, and the connection name added is **Local Purple Practice Splunk**.

1. Create a new diagnostic task and specify **`http://purple-lab-target:8080`** as the target. The older `http://juice-shop:3000` target can bypass the WAF, so we'll use the new hands-on task.
2. Specify the goal as narrow as checking whether `/ftp` public files/lists are accessible, and scope the check to only check this local target.
3. Opens details of the vulnerabilities found by the actual diagnostic. Existing vulnerability #3 will not be used by fixing it with the new WAF address.
4. In **Defense Validation**, save your detection hypothesis and defense plan and then select **Local Purple Practice Splunk** connection.
5. Press **Start ARTEX Diagnostics + Defense Verification**. The actual replay request is passed `X-ARTEX-Verification-ID` created by the server, and the same UUID should remain in the audit log and alarm.
6. After the diagnosis is completed normally, wait at least 60 seconds, check that log delivery/alarm processing is complete, and then click **Collect log/alarm**.

A successful connection test confirms communication/authentication of the Splunk management API. This does not mean that there are actual audit logs or detection alerts, so we collect and verify the basis for each execution.

The settings for the lab connection are as follows: The certificate SHA-256 fingerprint is the exact value seen by Splunk in the running lab, and is also stored in `.local-runtime/purple-lab/connector-template.json`, which has no secret value.

| Settings | value |
| --- | --- |
| index | `artex_lab` |
| thanks sourcetype | `artex:lab:audit` |
| alert sourcetype | `artex:lab:alert` |
| UUID field | `artex_verification_id` |
| Actual Action Field | `action` |
| read-only account | `artex_lab_search` |

The search account uses only the permissions necessary to query this index and check server information. Administrator authentication is used for initial configuration of Splunk in the lab and is not stored in the ARTEX connection. The index retention upper limit is 256 MiB·7 days, so in long-term practice, older records may disappear.

Every minute, the Splunk alert rule checks the last three minutes of actual WAF audit events for requests that match the `/ftp` protection rule `1001001` or the CRS SQL injection rule `942xxx`. All CRS matches are not replicated as alerts, and the original `rule_ids` is retained in the audit log. The alarm search time `_time` is the original time of the detection target request, and the alarm creation time is stored separately as `alert_created_at`. Rule execution and indexing may be delayed, so do not assume delivery is complete just by waiting 60 seconds after ARTEX ends, but check the alert/processing status before collecting. Late indexed alerts can be recollected in the same run.

## Three comparative exercises

The policy is set before starting a new revalidation and is maintained until log collection of that run occurs. When changing an alarm from off to on, the new activation time is recorded to ensure that requests for the section that was turned off are not retroactively detected in subsequent queries. Searches that have already started before you turn it off may complete, so check the status and send a new lab request. Create a new UUID launch using the same vulnerability and the same Splunk connection.

| Settings | command | Expected observations |
| --- | --- | --- |
| Just scan and generate an alarm | `mode detection`, `alerts on` | Actual alerts on UUIDs such as allow actions in audit logs |
| Block attacks and raise alarms | `mode blocking`, `alerts on` | Actual alerts on UUIDs, such as explicit blocking actions in audit logs |
| Just scan and turn off the alarm | `mode detection`, `alerts off` | Audit logs but no alerts for that UUID |

```sh
# 탐지되지만 요청은 통과하는 기준 실행
./scripts/purple-lab.sh mode detection
./scripts/purple-lab.sh alerts on

# 기준 실행과 근거 수집이 끝난 후 차단 정책 적용
./scripts/purple-lab.sh mode blocking
./scripts/purple-lab.sh alerts on

# 미탐 상황을 확인할 별도 실행
./scripts/purple-lab.sh mode detection
./scripts/purple-lab.sh alerts off
```

`mode` regenerates the WAF container, so after changing modes, it checks readiness and starts revalidating a new ARTEX. Wait for the next HTTP verification to succeed. This prepare request does not include an execution UUID.

```sh
./scripts/purple-lab.sh status
curl --fail --silent --show-error \
  -H 'Host: purple-lab-target:8080' \
  http://localhost:18790/healthz
```

The results in the table are expected values. ARTEX makes a decision after checking whether the actual request matches the rules, whether the diagnosis has been completed normally, and whether audits and alerts for the same UUID have been collected. Normal requests are not included in attack prevention expectations. If re-verification fails or is interrupted or there is no audit log, it is not confirmed as not detected. Blocking WAF is an effect of a front-end defense policy and is not evidence that the vulnerable code inside Juice Shop has been removed.

On the defense verification screen, select **Run baseline before improvement**, write down the applied policy changes, and start implementing improvements. Changing WAF modes and alert rules is a practice policy, and you can keep Splunk connection settings or vulnerability targets stored in ARTEX for comparison.

## Check the same basis with the file

```sh
./scripts/purple-lab.sh export \
  --uuid '화면에 표시된 실제 실행 UUID' \
  --start '2026-10-10T12:00:00+09:00' \
  --end '2026-10-10T12:05:00+09:00'
```

Replace the UUID and example times above with actual execution values. For the start and end times, enter an ISO 8601 value with a time zone, such as `+09:00` or `Z`, and includes 30 seconds before the start of execution to 60 seconds after the end. You can export the actual execution UUID and Splunk audit alert `_raw` for the corresponding time range to JSONL for file verification. Keep `audit.jsonl`, `alert.jsonl` and `manifest.json` in the output folder. The export does not automatically check the completeness of the collection, and `completeness_confirmed` in the manifest is the default `false`. If your practice has alerts turned off, make sure the alerts file is empty and select **No alerts in query range**. No logs or failed exports are not identified as No Alerts.

Field mappings for file uploads are specified by values ​​guided by the exporter. `target` in the log is the practice asset `purple-lab-target:8080`, and the Host value of the actual request is stored separately as `request_host`. The original ModSecurity audit log is stored in `evidence-local/purple-lab/logs/modsec_audit.log`, and the normalized audit log is stored in `audit.jsonl` in the same folder. `allowed` means that the WAF policy allowed the request and does not prove that the vulnerability was successfully exploited or that the response body was delivered successfully. Check full collection is selected only when audits and alarms from 30 seconds before the start of execution to 60 seconds after the end of execution are included and there are no collection gaps or limits exceeded. For the meaning and limits of file upload and Splunk query, please refer to [Defense Verification Guide](purple-validation.md).

## When the result is indeterminable

- **Diagnosis is still in progress or failed/aborted:** Check the LLM/object access and reproducibility in the diagnostics dialog. Verify with a new run that completed successfully.
- **No audit log with same UUID:** Checks whether the actual request went to the WAF front end address and whether the verification header was logged.
- **Missing Audit Log Action:** Map the `action` field containing the actual WAF action to the connection. Avoid using HTTP 403 as a blocking field instead.
- **No alerts:** Check whether the alert rule is active, rule condition matching and log forwarding respectively. Do not use simple log search results as alerts instead.
- **Late collection:** After delivery and retrieval processing is completed, re-collection is performed in the same run. The ARTEX inquiry section is fixed to 60 seconds after the end, so alarms with event times later than this section require separate investigation.
- **Search Warning/Row Limit Exceeded:** Re-verify with replay requests within 200 audits/alarms each. Partial results do not confirm non-detection.

To investigate historical attack flows, under **Breach Investigation → Prepare Log Evidence**, select the target's entire historical history instead of files narrowed down by UUID. You can use both Splunk direct query and file upload, detailed steps are in [Breach Investigation Guide](cert-investigation.md).

## Stop the lab environment

```sh
./scripts/purple-lab.sh stop
```

It only stops the lab environment and preserves your data. ARTEX and PostgreSQL are managed by existing run configurations. In the next lab, run `start` again and check the status, policy, and alarm settings.
