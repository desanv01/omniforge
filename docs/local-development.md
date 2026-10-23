# Local Docker development

This project is based on the Korean version of ARTEX and adds defense verification and agent infringement investigation. The default distribution runs **ARTEX and PostgreSQL** only. Currently, we build the Korean UI and Go backend directly from source, and no upstream ARTEX image is required. Juice Shop and Splunk are not installed.

## execution

After running Docker Desktop or Docker Engine and Compose v2, use the following command in the repository root: There is no need to install Go or Node.js separately on the host.

```sh
./scripts/local-start.sh
```

The first build will take some time as it downloads dependencies and Chromium. After completion, set the administrator password on <http://localhost:8787/setup/>. The LLM key can be set in the UI, and the initial setup screen opens without the key.

Port 8787 and logging proxy 8788 are only exposed to `127.0.0.1` on the local computer. The other containers are separate Compose projects and will not be stopped or changed by this configuration.

## operating instructions

```sh
# 상태
docker compose --env-file .env.local -f docker-compose.local.yml ps

# 로그
docker compose --env-file .env.local -f docker-compose.local.yml logs --tail=100 artex

# 중지: 데이터와 볼륨은 보존
docker compose --env-file .env.local -f docker-compose.local.yml stop

# 소스 변경 후 재빌드·기동
./scripts/local-start.sh

# 방어 검증·재검증·보관 기능 테스트: 별도 임시 DB 사용
./scripts/local-test.sh
```

## Data and Settings

- `.env.local`: DB password generated upon first run. If necessary, add preferences here, such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
- `.local-runtime/jwt.key`: The key used to sign logins and encrypt stored Splunk credentials. It must be preserved with the DB. If you lose or replace it, you will need to re-enter your Splunk authentication information.
- `data/`: Preserves working files and execution history.
- `artex-local_pgdata`: Docker volume that holds PostgreSQL data.
- `skills/`: Attaches a skill from the current repository to a container.

Secrets and runtime data are excluded from Git and source build contexts. If you print `docker compose config` without `--quiet`, the password may be displayed.

If another local app is using the default port, you can specify the port before launching.

```sh
ARTEX_LOCAL_PORT=18887 ARTEX_LOCAL_PROXY_PORT=18888 ./scripts/local-start.sh
```

In this case, the connection address is `http://localhost:18887`. Specify the same value for the next run or keep it in `.env.local`. If you verify different source checkouts simultaneously, you must also specify `ARTEX_PROJECT_NAME` and `ARTEX_LOCAL_IMAGE` separately to prevent containers, DB volumes, and images from being mixed.

This configuration is for development use only. Rebuild the current source with `local-start.sh` instead of automatically updating the UI upstream. The administrator password and LLM key are set by the user, and no diagnostics are run on the actual target until the task is created.

## Use first as file upload

The default connection method, **file upload**, is used in the defense verification of vulnerability details. Set the log source and time, UUID, action, and event ID fields and run ARTEX revalidation. After completion, if you register the audit/alarm JSON/JSONL/CSV file, you can view the judgment, confirmed problems, and probable cause. The file method does not require a Splunk account. ARTEX Diagnostics still requires an LLM setup and licensed audience.

If the export for the entire period has not been confirmed, or there is neither an alert file nor a no-alert confirmation, it is not assumed to be a non-detection. The original file text is preserved in the local DB, excluded from the list/comparison response, and included in the overall JSON export. For detailed usage order and support format, refer to [Defense Verification Guide](purple-validation.md).

### Create a physical file from an existing local Juice Shop

This section is a reproduction aid from a **separate lab environment** where public screen transcripts were created. Juice Shop is not included in the base product installation, and this step is not required to run and test new checkouts. The script below does not install Juice Shop itself.

For use only in a local configuration where `artex-practice-juice-shop-1`, already prepared separately from `artex-local-artex-1`, is running.

```sh
sh scripts/practice-logs-start.sh
```

Connects `http://juice-shop:3000` requests from ARTEX to the historical proxy while preserving existing Juice Shop containers and data. If you need to restore port connectivity in Docker Desktop, just restart the ARTEX container. To go through the proxy in your browser, use `http://localhost:8791`. Existing `8790` direct accesses will not be logged to this collector.

1. Wait at least 30 seconds after starting the collector. In the vulnerability defense plan, the actual applied `ftp-access-v1` path detection is written down.
2. Select **Upload File** and enter a name for the source. Keep the default field mappings and press **Start ARTEX Diagnostics + Defense Verification**.
3. After normal completion, wait 70 seconds, then specify the vulnerability number and export it.

```sh
python3 scripts/practice-export-latest.py 3
```

Insert `audit.jsonl` from the output folder into the audit log file and `alerts.jsonl` into the alarm file. Enter the collection range indicated in the command, confirm the entire collection, and press **Register file and confirm**. If the export is rejected, uncheck Confirm full collection and resolve the indicated cause. The file is stored in `evidence-local/juice-shop-defense/`, which is excluded from Git.

This collector executes simple path rules only for actual `/ftp` and subpath requests. It does not block requests, determine whether they are authenticated, or perform enterprise SIEM verification. `allowed` means that the proxy forwarded the response and does not prove that the original service's authority has passed. Incomplete responses are recorded as `unknown`. Configuration confirmation requests without a UUID are not included in the actual revalidation evidence, and confirmation requests with separate UUIDs are also excluded from export. The export uses only the actual run UUID and time, and confirms continuous collection with a 5 second heartbeat. If a collector stop, restart, or blank spans the interval, a new verification is required.

## Optionally connect to an existing Splunk

1. Under **Defense Validation → Splunk Log Connection**, enter the HTTPS address of your existing management API and your search account or token. ARTEX does not create new Splunk accounts or indexes.
2. Specify different audit/alert sourcetypes, UUID field `artex_verification_id`, and actual action field collected in one existing index. The execution UUID must be preserved in both the target audit log and the actual detection alert.
3. Save/activate the connection and confirm communication/authentication. When running with Docker, the management API must be accessible from the ARTEX container. `localhost` inside the container does not point to the host computer or any other Splunk container.
4. Set up LLM and open vulnerabilities found on authorized targets. After saving your defense plan, press **ARTEX Diagnostics + Start Defense Verification**. The UUID is only attached to requests to reproduce the original vulnerability, and is not attached to login or normal verification requests.
5. Evidence is collected 60 seconds after completion of diagnosis. If there is insufficient evidence, judgment remains impossible, and comparisons before and after improvement are made by connecting new runs with the same target, constraint, and source settings.

Connection testing alone does not complete diagnosis or verification of defenses. For detailed field settings, judgment criteria, and original text export, refer to the [Defense Verification Guide](purple-validation.md).

## Investigation of past log breaches

**Breach investigation** of vulnerability details is **1. Prepare log evidence → 2. AI investigation** Use in this order. First, specify the target, duration, and path as a file or existing Splunk connection and save the original evidence. This step of parsing/basic analysis does not require ARTEX-verified UUIDs or LLM concatenation.

After selecting the saved evidence and pressing **Start AI Investigation**, the ARTEX agent using the currently active LLM will iterate through hypothesis/action planning, read-only inquiry, textual confirmation, observation/inference, and follow-up planning. Selected vulnerability evidence and log excerpts are sent to the LLM you set up. The model is not called just by opening the page or saving the rationale.

File mode searches only stored events, and Splunk mode allows subsequent searches within the initially specified connection, destination, time, and path. We do not implement new penetration checks or operational policy changes. Missing logs are suggested as additional data, and observations, estimates, and data shortages are distinguished. Please refer to the [Infringement Investigation Guide](cert-investigation.md) for viewing limits, suspension, history, original text export, and result interpretation.

## Scope of Development Testing

`local-test.sh` runs in the `artex-purple-test` project, which is different from the actual app, and cleans up the test container and temporary DB at the end of the test. It inspects the revalidation life cycle, file parsing, range confirmation, action basis and cause diagnosis, SIEM response processing, evidence judgment and comparison, storage and restoration, and log playback. Agent investigation uses a mock model to check plan, query, source check, observation, follow-up plan, budget, stop, restart, Splunk follow-up query, scope, connection change check, and basis preservation. SIEM communication tests use HTTPS servers for testing purposes and do not diagnose with real targets or saved Splunk accounts. Build/test success is not considered actual detection/blocking success.

## By source

- Provided ZIP: `artex-ko-main.zip`, GitHub archive commit `867ea55c2690cdbc4cff8230325613d97b398bf7`.
- Current Git standard: `ee978f84f7a82ba87bbd04b33b766395559bf6cd` (`jiwoochris/artex-ko`).
- The core code and dependency files for both versions of the application are identical. The existing Git history and subsequent document/CI modifications were maintained.
- We maintain the copyright and AGPL-3.0 license of the original ARTEX and Korean version.
