# `/btw` Verification Record

Korean · [Chinese](VALIDATION.zh.md)

Date: 2026-09-10. Branch: `codex/btw-side-question`. Baseline commit: `8dae851b9b622f2ff2631f332fde9719d0b16fba`.

> This document is a translation of the original Chinese document (`VALIDATION.zh.md`) into Korean. The original is preserved so that changes in upstream repositories can be easily compared.

An independent PostgreSQL test DB and data directory were used. The actual model credentials were only injected into an independent test environment and were not written into the code or records, nor did the product base model change. Go 1.26.3, norma v0.3.6, Next.js 16.2.9.

The actual model dialogue, return objects, engineering assertions, and Qwen original screening text are stored in [validation-2026-09-10.json](validation-2026-09-10.json), and there are no API credentials in it.

## engineering inspection

All items below passed, the evidence in parentheses is the evidence test.

- Deep copy of structured messages and tool arguments: Passed (ground `TestCheckpointDeepCopyAndBoundaries`).
- Summary/compression request does not overwrite, issues complete response and exit status, excludes half-response during creation: Passed (evidence `TestCheckpointDeepCopyAndBoundaries`, `TestSnapshotExcludesPartialStreamAndSelectsPoolMember`).
- Physical Model Pool Member Identity: Passed (based on `TestSnapshotExcludesPartialStreamAndSelectsPoolMember`).
- Matching Tools, Playing 20 Bundles, Budget Cuts and Excess Errors: Passed (Based on `TestBuildRequestCompactionToolPairingAndBudget`).
- Parallel execution of main and side questions, two-way cancellation isolation: Passed (Reason: Blocking Provider, `TestMainSideConcurrencyAndIndependentCancellation`).
- No tool execution, streaming/non-streaming, existing usage at time of failure: Passed (based on `TestServiceNoToolsAndUsageOnFailure`).
- Actual norma ChatAgent and local Read tool, main transcript/activity isolation: Passed (based on streaming/non-streaming subcase of `TestSideActualChatCheckpointToolResultAndTranscriptIsolation`).
- Persistence, page breaks, idempotency, partial response preservation after restart: Passed (grounds `TestSideHistoryIdempotencyPagingAndRecovery`).
- Race between flush and belated write, delete parent resource, version comparison: Passed (grounded by `TestSideClearLateWritersAndDeletedParent`).
- MainAgent·Worker Archive and Restore (v1·v2·v3): Passed (based on `TestSideTaskArchiveVersions`).
- Delete three parent interfaces, authentication, resource attribution, worker logic: passed (grounds `TestSideHTTPGlobalLimitTaskWorkerAndDeletion`, `TestSideCheckpointPersistsBeforeAdmissionAndRestart`).
- Side questions are possible even in busy main sessions; independent SSE reconnection/disconnection, cancellation, emptying: passed (based on `TestSideHTTPBusyIsolationClearAndReconnect`).
- 1 per parent session, 4 global concurrent executions: Passed (evidence: two `TestSideHTTP…` cases).
- Save snapshot before submission, ask to continue after restart, prevent old sessions from forging snapshot: Passed (grounded by `TestSideCheckpointPersistsBeforeAdmissionAndRestart`).
- Refuse to continue if settings in cache are deleted or model is changed: Passed (grounded by `TestSideRejectsDeletedOrChangedCachedProfile`).
- Cancel before archiving and wait for final response and usage to be saved: Passed (based on `TestSideTaskDrainPersistsBeforeArchive`).
- Even if a streaming consumer cancels early, usage is recorded only once and attributed to the side question: Passed (based on `TestSideUsageRecordedOnceOnConsumerCancellation`).
- Worker·deadline execution context automatically restored by restart continues to issue new snapshots: Passed (grounds `TestSideRestoredWorkerRuntimePublishesNewCheckpoint`).
- Race check for related packages: passed (reason: command below).
- TypeScript and production build: Passed (based on `npx tsc --noEmit`, `npm run build`).
- Biome inspection of newly added frontend modules: Passed (based on `biome check`, 3 new modules).

You can reproduce the automated check by setting up `ARTEX_PG_DSN` on a separate database (do not point it to your production database):

```sh
go test -race ./agent ./db ./server ./sidequestion ./llmrec ./llmpool \
  -run 'Test(Side|Checkpoint|Snapshot|BuildRequest|Service|MainSide|CaptureRun|TaskArchive|CompleteForwards|StopIntent|CancelIntent)' -count=1
cd web
npx tsc --noEmit
npx biome check src/lib/side-questions.ts src/hooks/use-side-questions.ts src/components/side-question-workspace.tsx
npm run build
```

Not all Go regression tests are green. Two existing tests for the `server` package fail the temporary directory cleanup step, both reporting `TempDir RemoveAll … directory not empty`:

- `TestInheritedActivityDetailAndRelationDeletion`
- `TestTaskMetadataPatchReturnsRenameAndPin`

Even if you download the source from the unmodified base commit above and run the `server` package again in the same isolation environment, these two cleanup failures are identical. In the baseline commit execution, an assertion failure for the number of target nodes for `TestCoreTaskLifecyclePG` also occurred separately, but there was no assertion failure in the final revision's `server` regression. The other packages passed, and the case and race tests related to this side question also passed. We did not mark problems with the baseline commit as passing this review, nor did we change existing assertions to cover up hidden problems.

The Next.js build prints several existing warnings about lockfile·workspace root heuristics, but the build completes and all pages are created successfully.

## Browser check

We connected to an independent local Go service and Next.js development server with the Codex built-in browser. We performed the following manual and automated operations on desktop and 390 × 844 narrow screens and checked screenshots and browser logs:

- If you type `/btw` while regular chat is running, the main text and side questions are displayed simultaneously, and the desktop sidebar is also normal.
- Next, I asked an additional question. Even if you stop asking side questions, the parts already created remain, and the flow of the main text continues.
- Even if you close the panel, the request continues, and when you reopen it, the completed response will be restored. Refresh the page and simply enter `/btw` without any content to restore your history.
- In the narrow screen Drawer, input, button, record, and close operations are normal and there is no horizontal overflow.
- Emptying will display a confirmation pop-up, and after emptying, the record will disappear, but the main transcript and snapshot will remain.
- When I queried and switched between the MainAgent and the two Workers of a task, the agent tabs and records did not mix together.
- With the Worker running continuously as a blocking local model fixture, `/btw` was submitted to the Worker's main input window. Even after stopping the side question, the worker still displayed the real-time execution status and its own pause button, and the side question saved partial responses.
- The browser error/warning log is empty.

Controllable fixtures are intended to precisely verify concurrent execution timing and do not depend on the output speed of the actual model. During two worker execution checks during debugging, no valid concurrent execution section was created (the task was already finished or the response was finished prematurely), but I fixed the fixture and ran it again and it passed. This initial operation does not count as a valid pass.

## real model conversation

First, we detected `grok-4.6`. The OpenAI compatible interface is `http://127.0.0.1:12580/tingly/openai`. The detection returned model names `grok-4.6` and `READY` with HTTP 200 and took 2.82 seconds. Since the first rank was available, Tingly's `glm` or Zhipu's `glm-5.3` spare chains were not turned on, and these two spare services were not verified at this time.

- While the main session was running, asked for assets/goals/markers: `redhaze.top`, read the first page and summarized the goals, returned `BTW-REAL-0910`, and side questions completed (16.97 seconds).
- After the main session has finished reading the first page, the tool asks for the rationale: WebFetch 200, curl's 301 → 302 → 200 redirect, quoting the page title exactly (7.24 seconds).
- A side question asked to create a test file in Bash: it refused to run and the target file was not created (7.74 seconds).
- The side question after completion does not change the main context: the SHA-256 of the main transcript and the main activity record match, and the number of tool executions for the side question is 0.
- After actually stopping and restarting the Go service, follow-up questions: We preserved the 3 previous side question records and answered the assets/markers/titles directly from the persisted snapshot, without running the main agent again.
- Using Grok non-streaming settings in a new session: answered assets and `ATOMIC-0910` correctly, and returned/stored usage (input 11734, output 138, cache_read 11520).

The main session of the asset example read the first page published with WebFetch and Bash/curl, the landing page was `https://id.redhaze.top/home`, and the title returned by the page was "RedHaze Group·全球综合集团门户" (quoted as it is the original text returned by the model). Bash only briefly saved the response to a local test file and did not write it remotely. This fact was confirmed separately from the fact that "the side question did not run the tool."

Main transcript verification value: `e7e61f135a4a120954b539f357e8c4205d7d5cd7460dcaf3dc0fd066463e1d00`.

**Usage Limit:** Tingly's Grok streaming response did not return usage. When `stream_options.include_usage=true` was sent and verified separately, it was HTTP 200, 12 data frames, and 0 usage frames. Therefore, a 0 in the streaming test means that the endpoint is not providing usage and should not be interpreted to mean that there were no charges. Non-streaming usage and fixture failure/cancellation usage were all saved correctly.

## Qwen screening

The screening model is `qwen-flash`, and the OpenAI compatible interface is `https://dashscope.aliyuncs.com/compatible-mode/v1` and HTTP 200. We provided the previous three actual side question conversations, a tool rationale for the main session, and an engineering assertion, and returned `verdict: accept` and `concerns: []` . We determined that the response matched the asset, marker, and page reading evidence and that the side question tool rejection met the constraints. Screening usage: prompt 6625, completion 312, total 6937.

The scope of this Qwen review does not include service restart and non-streaming tests that were added later. Qwen's generalization of "no writing" is overly broad. curl in the main session actually created a local response temporary file, which we clearly logged earlier. Concurrency, 0 tool executions, and transcript isolation are judged by engineering assertions, and model screening only aids in assessing response quality.
