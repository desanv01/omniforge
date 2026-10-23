# Optional WAF·Splunk hands-on verification record · 2026-10-10

In a local lab environment separate from the default ARTEX·PostgreSQL installation, we checked the WAF in front of Juice Shop, actual audit log collection, Splunk detection rules, and ARTEX log queries. This check is an independent environmental check and does not complete an ARTEX AI diagnostic or revalidation run on your behalf. Instructions for execution are in the [Practice Guide](../purple-lab.md).

## Verification environment and scope

- Separate Compose projects: Juice Shop·ModSecurity/OWASP CRS WAF·Log Collector·Splunk by `artex-purple-lab`.
- Diagnosis target: `http://purple-lab-target:8080`. The browser address is `http://localhost:18790` and it goes through the WAF.
- Actual logs: WAF native audit raw text was normalized and collected as `artex:lab:audit` in the `artex_lab` index. The alarm was recorded in `artex:lab:alert` as a log event action of the actual Splunk saved search.
- Search account: `artex_lab_search` to query only the lab index. ARTEX connected to the management API with the correct lab certificate SHA-256 pin.
- The collector authentication mount was limited to read-only access to the two files, HEC token and certificate pin. The administrator/search account password folder is not passed on to the collector.
- Existing vulnerability number 3 and the original target `juice-shop:3000` were not changed. WAF assets are newly registered.

In each case, we sent one search request containing the normal control request `/`, the information exposure path `/ftp/acquisitions.md`, and the SQLi pattern. `/ftp` protection is explicit practice rule `1001001` and SQLi check confirmed standard CRS rule `942100`. Alerts are generated for these two types of matching conditions.

## Real environment verification results

`./scripts/purple-lab.sh check` compared actual WAF actions and Splunk search results.

| Case | WAF mode/alarm | Appreciation Event | Real Splunk Alerts | Action confirmed |
| --- | --- | --- | --- | --- |
| Detection only | DetectionOnly·on | 3 | 2 | Allow both normal and inspection target requests, check alerts for both inspection target requests |
| Actual blocking | On·on | 3 | 2 | Allow 1 normal request, block 2 scanned requests, check both blocking alerts |
| Alarm inactive | DetectionOnly·off | 3 | 0 | 3 audits allowed, no alerts from these runs |
| Total | Request 9 | 9 | 4 | Total of 13 audits and alerts |

Normal collation request passed without WAF rule match. Interception was confirmed based on explicit interception in native audit logs and active engine mode, rather than inferred from HTTP status codes alone. The alert's original audit ID, UUID, action, time, and rule list also matched the corresponding audit event. After the scan, the policy was restored to DetectionOnly·Alert on.

The backend response for detection-only SQLi requests was HTTP 500. What we see here is SQLi pattern detection and WAF policy action, and does not demonstrate successful SQLi exploitation or data exfiltration. Blocking the `/ftp` path is also an effect of the front-end policy and is not evidence that the vulnerable code inside Juice Shop has been removed.

![13 actual audits and alerts confirmed by search-only accounts](images/06-purple-lab-splunk.jpg)

## Actual View of ARTEX Connectors

New Lab I ran `securitysource.Fetch` with a search-only account in Splunk. The execution UUID of each case and the time from 30 seconds before start to the time of inquiry were specified, and no changes were made to the operational DB or existing logs.

| Case | Collection Event | Audit/Alarm | View completed | Search Alert | Action distribution |
| --- | --- | --- | --- | --- | --- |
| Detection only | 5 | 3·2 | true | 0 | allowed 5 |
| Actual blocking | 5 | 3·2 | true | 0 | allowed 1·blocked 4 |
| Alarm inactive | 3 | 3·0 | true | 0 | allowed 3 |

`blocked 4` in the blocking row is the number of events, which is the sum of 2 audits and 2 alerts for both requests. This doesn't mean that four requests were blocked. The actual Splunk exit response with 0 alerts was also interpreted as a normal completion.

The past investigation function `FetchInvestigation` was also executed from 30 seconds before the start of the last case until the time of inquiry. Target is `purple-lab-target:8080`, path is full, not narrowed down by UUID. **20 collected, true hits, 0 invalid events** confirmed, and the regenerated query with the saved field mapping was the same as the original query. These 20 cases are the results of searches for the relevant period and target, and their scope is different from the 13 cases in the three cases above.

Actual Splunk JSON automatic extraction and duplicate identical values ​​that occur in `spath` are removed with `mvdedup`. It is treated conservatively by preserving different values, and does not discard existing extracted fields in plain text. We ask that search results times include a numeric offset and microseconds to avoid guessing ambiguous time zone abbreviations.

After rebuilding the modified app, I re-ran `connect` to reuse the same lab connection, and also confirmed a successful connection test on the ARTEX screen. The connection test is the result of checking communication and authentication of the management API. Separately from the screen below, I performed the actual query of the above collection function.

![Local Purple practice Splunk connection registered with ARTEX](images/07-purple-lab-artex.jpg)

## Unit/regression test

| inspection | Verification result |
| --- | --- |
| Python collector unit test | 27 passed |
| Python Splunk initial configuration·TLS·detection state unit testing | 15 passed |
| Python sum | 42 passed |
| `go test ./securitysource ./investigation -count=1` | Two packages passed; Time offset·Query range·Conflicting multi-value·0 completed·Query regeneration Includes regression |
| `go vet ./securitysource ./investigation` | passed |
| `./scripts/local-test.sh` | Full isolation regression check with separate temporary PostgreSQL exit code 0; 156 top tests, 0 failures |
| Rebuild/reconnect local ARTEX app | Build exit code 0, reuse existing lab connection and confirm successful connection test on screen |

The Go check for this record was run in a temporary container/test DB separate from the operational DB. The actual Splunk query only made read requests to the lab instance separately. The final status was WAF DetectionOnly, Splunk/Collector healthy, 0 pending delivery.

After limiting the collector secret mounts to two files, I recreated the container and also verified that an audit of new normal requests actually made it to Splunk. Even if `alerts on` was re-run on an already activated alarm, the existing detection start time and query were maintained. `off → on` transition only sets a new start time.

## Disclosed data and limitations

The public data is the actual screen, result values, and verification range. Does not include API key, password, JWT/private key, original audit log, full search export, or operational DB. Original verification records and full logs are stored in `evidence-local/purple-lab/`, excluding Git, and practice authentication information is stored in `.local-runtime/purple-lab/`.

The UUIDs and logs generated by this independent verification command will not be submitted on your behalf as the basis for another ARTEX revalidation. The actual ARTEX verification is performed using the vulnerabilities discovered by the new WAF diagnostic and the UUID of the corresponding execution. This verification does not guarantee detection accuracy in the corporate environment, occurrence or non-occurrence of past breaches, completion of AI investigation, or automatic incident confirmation.
