# Vulnerability and multiple traffic evidence

The "associated traffic" of vulnerability details supports cross-page multiple selection, purpose and description, sorting and unbinding. You can also select multiple records on the traffic page and associate them with one existing vulnerability at a time. The vulnerability evidence inherited by the task is read-only, and modification requires entering the source task.

The "Agent automatic binding traffic" in the system settings is turned off by default, and the interface is read and modified `agent_traffic_binding` of `/api/settings`. Enabling it will increase the token consumption caused by query requests/responses, tool calls and prompt words; the next round of Agent will use the new settings. When closed, the auto-binding parameters and re-binding tools are hidden, auto-binding guidelines are not injected, and newly submitted auto-bindings from running sessions are rejected. Manual binding, traffic capture, saved evidence reading and exporting are not affected.

After it is turned on, the default process is "Discover the database → Automatically trigger the report Agent → Check and bind the traffic → Write the report according to the latest evidence version". The reporter keeps the verification command, key output, existing real traffic ID and purpose in `evidence`; the reporting agent combines the vulnerability details and execution records, verifies it with `traffic_search` / `traffic_get`, calls `bind_finding_traffic`, and then reads the latest `version` to save the report. When the switch is turned off, the reporting agent does not obtain additional raw traffic retrieval/reading tools, nor is it automatically bound; it can still read manually bound snapshots and generate reports.

Compatible with existing callers: `traffic_refs` / `evidence_hint_id` of `report_finding` can still be explicitly bound on the fly. Binding is optional: When non-HTTP vulnerabilities such as TCP are not collected or the exact record cannot be found, omitting the reference can still report and write reports normally; retain command output, logs and other verifiable evidence. It is recommended to explain the reason for unbinding and do not add required fields. Submitted IDs must all be valid and the text must be complete. If any one of them fails, the binding operation will be rolled back; if an explicit reported binding failure occurs, the entire report will be rolled back. Repeatedly appending the same snapshot does not increase the binding and does not overwrite the description.

## Agent number and report version

`report_finding` adds a new optional parameter, the array order is the initial evidence order:

```json
{
  "traffic_refs": [
    {"traffic_id": "真实流量ID", "role": "baseline", "note": "正常账户请求"},
    {"traffic_id": "另一个真实流量ID", "role": "proof", "note": "复现请求"}
  ]
}
```

The uses are `baseline` (normal control), `proof` (vulnerability proof), `verification` (supplementary verification), `supporting` (auxiliary evidence, default). First use `traffic_search` / `traffic_get` to check the real record; the domain name and time are only used for candidate screening, and task ownership is not presumed.

For the prompt words, refer to [CyberStrikeAI's Vulnerability Reporting Tool Guide](https://github.com/RuoJi6/CyberStrikeAI/blob/54d56774b8bd285817d16d48b70a4a5e6e0963f7/internal/app/vulnerability_tools.go), combined with the optional binding convention of this project, no mandatory verification due to no package is introduced. IDs should not be guessed, nor should probing be repeated just for patch packets.

The first line returned is still `finding recorded: <探索节点 ID>`; subsequent JSON provides the independent vulnerability record `finding_id`, exploration node `finding_node_id`, and binding summary.

- `get_finding_traffic(finding_id)` uses **independent vulnerability record ID** to return an ordered list and `version`; `binding_id`, `side=request|response`, `offset`, and `length` can be read in segments, with each segment up to 8192 bytes.
- `finding_id` of `update_finding_report` **Continue using the exploration node ID**. Added `evidence_version` to fill in the actual read version; if the evidence changes during generation, the old version will be rejected and must be re-read and generated.
- When the old report calls the untransmitted version, it does not claim to cover existing traffic evidence. After the binding, description, usage or ordering changes, there are reports indicating that they need to be updated.

After turning on automatic binding, `add_hint` / `add_task_hint` supports saving `traffic_refs` in each element of a single prompt or batch `hints`. Planner can upload `evidence_hint_id` when reporting on your behalf, and explicitly select the reference in the prompt corresponding to this task. Inherited prompts cannot be quoted. The system will not guess binding based on domain name, time or browsing history. Failed submissions do not generate partial vulnerability or early trigger reports.

If there is an existing vulnerability that has been missed, you can use `bind_finding_traffic(finding_id, traffic_refs)` to patch it up without having to register again. `list_findings` / `list_task_findings` / `node_detail` / `get_task_node_detail` return explicit `finding_id` and `finding_node_id`; old `id` maintains explore node semantics.

Only optional attributes are added to the old tool schema at startup, and the original default traffic tool binding is extended to the reporting agent; the re-binding tool is handed over to the reporting agent by default. Customized binding list, prompt words, description and enabled status retention. Guidelines will be added after the final tool is assembled: the reporting role is responsible for handing over existing evidence, and the reporting agent is responsible for checking, binding and writing reports. When the platform dialogue lacks task context, it should be handed over to the task agent through structured prompts and should not be reported directly. The existing evidence should be handed over before judging that the task is completed; there is no compulsion to wait if there is no package. A failed `report_finding` does not trigger the reporting agent.

## API

Base path: `/api/exploration/findings/{finding_id}/traffic`, using independent vulnerability ID. Inherit authentication; `context_task` verification task visibility and inheritance read-only.

| Method / relative path | request / return |
| --- | --- |
| `GET` | Ordered summary, evidence version, report adoption version |
| `POST` | `{"traffic_refs":[...]}` Added adjustment |
| `PATCH /{binding_id}` | `{"version":1,"role":"proof","note":"说明"}` |
| `DELETE /{binding_id}` | `{"version":1}` |
| `PUT /order` | `{"version":1,"binding_ids":["2","1"]}`, must be a complete list |
| `GET /{binding_id}` | Snapshot metadata and bounded text preview |
| `GET /{binding_id}/body` | `side`, `offset`, `length`; `download=1` Download complete original bytes |

Version/sort set conflict, writing in archive returns `409`; inherited writing `403`; binding that does not exist or is not a vulnerability `404`; traffic/attachment reading and verification failure clearly returns an error.

## Storage and migration

Start idempotent migration PostgreSQL: Added `traffic_evidence_snapshots`, `finding_traffic_bindings`, and `findings.evidence_version` / `report_evidence_version` (default 0). Do not make guesses based on historical texts.

The snapshot saves the original traffic ID, collection time, URL, method, status, request/response headers, body length, and SHA-256. The body is hashed in `<data>/evidence/blobs/<前两位>/<hash>.bin`, independent of the cleanable `data/traffic`, and multiple vulnerabilities can share snapshots/text. Snapshots do not provide a content update interface, and reading and exporting fail when the verification is inconsistent.

Read the complete text, including large text blobs and old directory records, under raw traffic write lock. The file is persisted and verified first, then a single PostgreSQL transaction is used to write exploration nodes, intent relationships, vulnerabilities, snapshots, and bindings; the planner is notified only after submission. Failure may leave no referenced files, but no partial business records will be generated.

PostgreSQL advisory lock `7337741004` reconciles evidence files and SQL references; task row lock prevents archive queued evidence modifications. Recovery maintains evidence locks throughout the entire process from text installation to metadata submission. Delete vulnerability cascade removes bindings.

The cleaner runs hourly and only reclaims content that has no references and is not an ongoing operation, with a minimum delay of 24 hours. Ordinary traffic cleaning does not touch the evidence directory. Back up PostgreSQL and `data/evidence` at the same time when backing up hot data.

## Export and archive

Markdown contains ordered evidence lists and versions; JSON contains metadata; CSV adds quantities and binding IDs. `md-zip` retains vulnerability Markdown and provides:

```text
evidence/<finding_id>/<binding_id>/
  manifest.json
  request.http
  response.http
  request.bin
  response.bin
```

Markdown references messages via relative links. Attachment copying, hash verification, compression, disk synchronization and CRC reading verification of all ZIP entries are completed before sending for download; missing/damaged files will cause the entire download to fail. Complete attachments retain binary raw bytes.

Archive v3 collects snapshots and texts based on vulnerability binding relationships, without relying on original traffic or domain names. Hot data is cleared only after package verification is completed; shared evidence continues to be retained. During recovery, the installation text is first verified, and then the metadata and bindings are restored. Failure retry is supported. v1/v2 continues to be recoverable, and missing new fields are explicitly filled with 0.

## Validation and Boundaries

Set up an independent, newly created PostgreSQL test library for each test package, specified via `ARTEX_PG_DSN`, to avoid residual tasks/model fixtures from triggering background runs. Run a complete test of the relevant packages and confirm that there are no skips caused by missing configuration:

```sh
# 每个包运行前将 ARTEX_PG_DSN 设为对应的独立测试库；显式配置失败必须报错。
go test ./<package> -count=1
go test -race -p 1 ./evidence ./db ./agent ./server -run 'TestEvidence|TestFindingTraffic|TestFindingEvidence|TestReportFindingAtomicContract|TestTaskArchive'
```

Front-end validation includes `npx tsc --noEmit`, Biome checks of affected files, Webpack builds, and `NEXT_EXPORT=1` static exports. Use a separate cache directory to avoid overwriting running development services.

Native end-to-end acceptance uses independent ports, controlled HTTP/domain name HTTPS targets and temporary data directories, covering two binding entries, cross-page selection, sorting/description, error prompts, inheriting read-only, downloading, and exporting after deleting the original traffic, archiving, recycling hot text, recovery and verification of hashes.

The first version uses a global evidence coordination lock; during large batch binding/export or slow attachment download, other evidence operations may wait. Evidence cannot be made up in the absence of recording records or complete text. This function does not change the capture switch, nor does it deal with the certificate issue of HTTPS direct access to IP.
