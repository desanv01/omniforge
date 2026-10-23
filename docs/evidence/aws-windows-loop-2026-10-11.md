# AWS Windows Real Closed-loop Verification — 2026-10-11

We connected our previously owned AWS Windows Server and Splunk to AegisLoop Web's **Closed-loop → AWS Windows Lab**, and performed criteria execution, collection, candidate proposal, rule application, re-execution, and original export in the browser.

| Practical Execution Techniques | Baseline Rules | New run after applying improvement rule |
|---|---|---|
| Current user navigation — T1033 | Check actual alerts | Check actual alerts |
| Exploring the running process — T1057 | Alert unconfirmed | Check actual alerts |
| Exploring system information — T1082 | Alert unconfirmed | Check actual alerts |
| Scenario where alert is confirmed | **1/3** | **3/3** |

![Comparison of real alarms before and after in AWS Windows practice](images/aws-windows-loop-2026-10-11.jpg)

## Implementation and rationale

- Last comparison cycle: `5a8cc2ff-2850-4b50-bfa3-ccc59011fd0d`, candidate revision 2.
- Base run: 2026-10-11 09:16:12–09:16:24 KST. Rerun: 09:19:59–09:20:12 KST.
- In each run, three frozen atomics completed with exit code 0. I checked the different execution IDs and the actual Sysmon ProcessGuid lineage.
- The baseline rule detected `whoami.exe`. The candidate was actually distributed in a separate exercise saved search by adding the `systeminfo.exe` and `tasklist.exe` path conditions observed in the standard run.
- It was confirmed that the actual scheduled search for each step was completed normally and included the execution time range. The actual `logevent` alarm with matching search expression, rule hash, host, and ProcessGuid was used for judgment.
- Alerts from the actual atomic process that executed `whoami /all` were also checked separately for each baseline and re-execution. Because the auxiliary processes of the execution module are included in the log, the number of events and the number of scenarios are different.
- Both collections were confirmed complete, 0 warnings, and 0 no verdicts. Even after restarting the connector, the comparison results and history were maintained.
- 2,438,027 bytes of original evidence was downloaded and verified using **evidence JSON export** on the web. SHA-256 for this first download: `2c9d3d94fca0f4ed366f6c26dab3232b630ae6f9892e9a74ab603fe0d3ee9f6f`. The hash of the re-download may vary as it includes the export time.

Original Windows logs and administrative credentials are not included in the public repository. The original is stored in the local `evidence-local/aws-windows-loop-2026-10-11/`, and there is no account, access key, or public address on the public screen. Errors in the rule distribution path and reserved search prefix discovered during development were corrected, and previous executions were excluded from the final comparison sample.

## Verification scope

These results demonstrate the fixed **practical alert improvement** of the three search techniques. Since there is no normal business sample, it does not prove the false positive rate, precision, or detection performance of the entire corporate environment. It is not a result of verifying successful vulnerability exploitation, credential theft, AD lateral movement, or EDR blocking.

Related verification: Passed 14 bridge/origin attribution/scheduled search/authentication/restart regressions, 6 Go connection API regressions, and 9 HTTP rule helper regressions. Passed web static build and TypeScript inspection.

For installation and use procedures, refer to the [AWS Windows Practice Guide](../aws-windows-loop.md).
