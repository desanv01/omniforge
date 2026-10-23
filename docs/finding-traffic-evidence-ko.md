# Vulnerability Multiple Traffic Evidence

> This document is a Korean translation of the upstream (original) ARTEX design document. Linking Vulnerabilities and Traffic Evidence
> Organize the functional design for contributors and maintainers. The original text (Chinese) is
> It is saved in [`finding-traffic-evidence-zh.md`](finding-traffic-evidence-zh.md).
>
> English: **[Vulnerability multi-traffic evidence (finding-traffic-evidence-en.md)](finding-traffic-evidence-en.md)**.

“Connected Traffic” on the vulnerability detail screen supports multiple selection across multiple pages, input of purpose and description, sorting, and unbinding. The Traffic page also allows you to select multiple records at once and link them to a single existing vulnerability. Vulnerability evidence inherited by a task is read-only, and modifications require entering the original task.

The default value for “Agent automatic traffic binding” in system settings is off, and the read/modify interface is `agent_traffic_binding` of `/api/settings`. If you turn on this feature, token consumption resulting from request/response queries, tool calls, and prompts will increase, and the new settings will be used from the next Agent. When off, it hides autobinding parameters and supplemental binding tools, does not inject autobinding instructions, and rejects newly submitted autobindings from already running sessions. Manual binding, traffic capture, and reading and exporting of stored evidence are not affected.

The basic flow after turning on the function is “Save findings → Auto-trigger Report Agent → Traffic collation/binding → Create report with the latest evidence version.” The reporter leaves verification commands, key outputs, and the actual traffic ID and purpose already obtained in `evidence`. The Report Agent compiles vulnerability details and execution records, checks `traffic_search` / `traffic_get`, calls `bind_finding_traffic`, reads the latest `version`, and saves the report. If you turn off the switch, the Report Agent will not receive any additional source traffic search/reading tools and will not perform automatic binding, but will still be able to read manually bound snapshots and generate reports.

It is also compatible with existing callers. You can still explicitly bind `report_finding` to `traffic_refs` / `evidence_hint_id` immediately. Binding is optional. If it's a non-HTTP vulnerability, such as TCP, or you haven't collected it yet, or if you can't find the exact record, you can omit the reference and report it as normal. It is recommended that you leave other verifiable evidence, such as command output and logs, and explain the reason for not binding, and do not add new required input fields. All submitted IDs must be valid and the text must be complete. If any of them fail, this entire binding operation is rolled back. If you explicitly bind with a report and fail, it rolls back the entire report. Adding the same snapshot multiple times does not increase the binding and does not overwrite the description.

## Agent ID system and report version

A new selection parameter has been added to `report_finding`, and the arrangement order is the initial evidence order:

```json
{
  "traffic_refs": [
    {"traffic_id": "실제 트래픽 ID", "role": "baseline", "note": "정상 계정 요청"},
    {"traffic_id": "다른 실제 트래픽 ID", "role": "proof", "note": "재현 요청"}
  ]
}
```

The uses are `baseline` (normal control), `proof` (vulnerability proof), `verification` (supplementary verification), and `supporting` (supplementary evidence, default). First, we compare the actual record with `traffic_search` / `traffic_get`. Domain and perspective are used only to identify candidates and do not determine work attribution.

The prompt refers to [CyberStrikeAI's Vulnerability Reporting Tool Guide](https://github.com/RuoJi6/CyberStrikeAI/blob/54d56774b8bd285817d16d48b70a4a5e6e0963f7/internal/app/vulnerability_tools.go) and combines it with this project's optional binding protocol, but does not have a rule to mandatory verify the reason for not binding. IDs should not be guessed, and detections should not be repeated just to fill in the evidence.

The first line of the return value is still `finding recorded: <탐색 노드 ID>`. The JSON that follows provides `finding_id` for the independent vulnerability record, `finding_node_id` for the navigation node, and a binding summary.

- `get_finding_traffic(finding_id)` takes an **independent vulnerability record ID** and returns an ordered list and `version` . If you exceed `binding_id`, `side=request|response`, `offset`, and `length`, you can read it divided into sections, and one section can be up to 8192 bytes.
- `finding_id` in `update_finding_report` **continues to use the navigation node ID.** The newly added `evidence_version` is populated with the version actually read. If the evidence changes while the report is being generated, the old version will be rejected and must be re-read and generated.
- If an old report call doesn't override the version, it won't show that any existing traffic evidence has been overwritten. Changes in binding, description, purpose, or alignment flag existing reports as requiring updates.

When you turn on autobinding, `add_hint` / `add_task_hint` supports storing `traffic_refs` in each element of `hints` as a single hint or in batches. When the planner reports on your behalf, you can pass `evidence_hint_id` to clearly select references in the hint corresponding to this task, and cannot reference inherited hints. The system does not guess bindings based on domain, time, or lookup history. A failed submission creates a partially created vulnerability or does not trigger a report ahead of time.

If the binding is missing for an existing vulnerability, you can make up for it with `bind_finding_traffic(finding_id, traffic_refs)` and there is no need to register again. `list_findings` / `list_task_findings` / `node_detail` / `get_task_node_detail` returns definite `finding_id` and `finding_node_id`, and the old `id` retains the navigation node meaning.

At startup, only optional properties are added to the old tool schema, the original default traffic tool binding is extended to the Report Agent, and the supplemental binding tools are left to the Report Agent by default. Custom binding lists, prompts, descriptions, and activation status remain intact. Instructions are added all at once after final tool assembly is completed. The reporting role is responsible for handing over evidence already obtained, and the reporting agent is responsible for collating, binding, and writing reports. When there is no task context in the platform conversation, it must be passed to the task agent as a structured hint and is not reported directly. It must first hand over evidence that is already present before determining that the operation is complete, and will not force you to wait if there is no traffic to bind. A failed `report_finding` does not trigger the Report Agent.

## API

The default path is `/api/exploration/findings/{finding_id}/traffic` and uses an independent vulnerability ID. Authentication follows the traditional method, and `context_task` verifies task visibility and whether the inheritance is read-only.

Requests and returns for each method and relative path are as follows:

- `GET`: Returns the ordered summary, evidence version, and version accepted by the report.
- `POST`: Add `{"traffic_refs":[...]}` all at once.
- `PATCH /{binding_id}`: Modify to `{"version":1,"role":"proof","note":"설명"}`.
- `DELETE /{binding_id}`: Delete as `{"version":1}`.
- `PUT /order`: Sort by `{"version":1,"binding_ids":["2","1"]}` and must be a complete list.
- `GET /{binding_id}`: Returns snapshot metadata and a limited-length body preview.
- `GET /{binding_id}/body`: Receive `side`, `offset`, `length`, and if it is `download=1`, download the complete original bytes.

A version/alignment set conflict or an archive in progress write will return `409`, a write to an inheritance will return `403`, and a binding that does not exist or is not part of the vulnerability will return `404`. If the traffic/attachment read and validation fails, it returns an error clearly.

## Storage and Migration

Performs an idempotent migration to PostgreSQL at startup. Add new tables `traffic_evidence_snapshots`, `finding_traffic_bindings` and `findings.evidence_version` / `report_evidence_version` (default value 0) columns. Don't guess complementary bindings based on past text.

Snapshots save original traffic ID, collection time, URL, method, status, request/response headers, body length, and SHA-256. The text is stored in `<data>/evidence/blobs/<앞 두 자리>/<hash>.bin` according to the hash, and is separated from `data/traffic`, which is the subject of cleaning, so multiple vulnerabilities can share the snapshot/text. Snapshots do not provide a content update interface, and reads and exports will fail if validation does not match.

Under the source traffic write lock, the entire body is read, including large body blobs and old directory records. It first persists and verifies the files, then records navigation nodes, intent relationships, vulnerabilities, snapshots, and bindings in a single PostgreSQL transaction, and only after committing, notifies the planner. Failure may leave unreferenced files, but will not create partial business records.

PostgreSQL advisory lock `7337741004` coordinates the evidence files and SQL references. A task row lock prevents modification of evidence after it has been placed in the archive queue. Restore maintains an evidence lock throughout the entire process, from body installation to metadata commit. Deleting the vulnerability will also cascade the binding.

The pruner runs hourly, reclaiming only the contents of tasks that have no references and are not in progress, but with a delay of at least 24 hours. Regular traffic pruning does not touch the evidence directory. When backing up hot data, back up PostgreSQL and `data/evidence` together.

## Export and Archive

An ordered list of evidence and versions are added to Markdown, metadata is added to JSON, and counts and binding IDs are added to CSV. `md-zip` maintains the vulnerable Markdown and provides the following structure:

```text
evidence/<finding_id>/<binding_id>/
  manifest.json
  request.http
  response.http
  request.bin
  response.bin
```

Markdown refers to packets by relative links. Before sending your download, we'll copy attachments, verify hashes, compress, sync to disk, and read-verify the CRC of all ZIP items. If any item is missing or corrupted, the entire download will fail. A complete attachment preserves the binary original bytes intact.

Archive v3 collects snapshots and bodies based on vulnerability binding relationships and does not depend on the origin traffic or domain. Only after package verification is completed, hot data is cleaned up and shared evidence is still preserved. Restoration first verifies the installed body and then restores metadata and bindings as a transaction, and supports retry if failure. v1/v2 can also still be restored, with any new missing fields explicitly filled with 0.

## Verification and boundaries

Have a newly created PostgreSQL test database independent of each test package and specify it as `ARTEX_PG_DSN` to ensure that any remaining task/model fixtures do not trigger background execution. Run full tests of the relevant packages, making sure no tests are skipped due to missing settings:

```sh
# 각 패키지를 실행하기 전에 ARTEX_PG_DSN 을 해당 독립 테스트 데이터베이스로 설정합니다. 명시적 설정이 실패하면 반드시 오류를 내야 합니다.
go test ./<package> -count=1
go test -race -p 1 ./evidence ./db ./agent ./server -run 'TestEvidence|TestFindingTraffic|TestFindingEvidence|TestReportFindingAtomicContract|TestTaskArchive'
```

Frontend verification includes `npx tsc --noEmit`, Biome inspection of affected files, Webpack build, and static export of `NEXT_EXPORT=1`. Use an independent cache directory to avoid overwriting a running development server.

Local end-to-end argument validation uses independent ports, controlled HTTP / domain HTTPS destinations, temporary data directories, and covers two binding entry points, selection across multiple pages, sorting/description, error guidance, inheritance read-only, and downloads. It also includes export, archiving, hot body retrieval, restoration and hash verification after discarding the original traffic.

The first version uses global evidence coordination locking. Other evidence tasks can wait while a bulk bind/export or slow attachment download occurs. Without recorded records or complete text, evidence cannot be fabricated. This feature does not change the capture switch, nor does it address certificate issues when accessing IP directly over HTTPS.
