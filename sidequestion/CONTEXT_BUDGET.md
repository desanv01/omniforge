# Side Questions Long Conversation and Context Budget

Korean · [Chinese](CONTEXT_BUDGET.zh.md)

Edited 2026-09-11. The previous implementation considered the number of characters in the request JSON as the number of tokens and inherited the 32K output reservation from the main task, so there was a problem with normal side questions being rejected in advance when there were many HTML, JS, and tool results.

> This document is a translation of the original Chinese document (`CONTEXT_BUDGET.zh.md`) into Korean. The original is preserved so that changes in upstream repositories can be easily compared.

## Open source implementation comparison

- [Grok CLI Side Question Context](https://github.com/superagent-ai/grok-cli/blob/fb97af83f06dca873281d60168430f06c8de6324/src/agent/agent.ts#L739): Snippets are extracted from the most recent user/assistant text, with a character budget of approximately 2000 characters, truncated to a maximum of 400 characters per occurrence. This route does not maintain a continuous record of side questions.
- [Grok CLI Independent Request](https://github.com/superagent-ai/grok-cli/blob/fb97af83f06dca873281d60168430f06c8de6324/src/utils/side-question.ts): Set aside cancel signal. If the model supports it, the output upper limit is 2048 tokens. No tools are provided.
- [Grok CLI Main Session Compression](https://github.com/superagent-ai/grok-cli/blob/fb97af83f06dca873281d60168430f06c8de6324/src/agent/compaction.ts): Estimates tokens, leaves recent content, reflects new content into previous summaries, and handles truncation across turn boundaries.
- [OpenCode Session Compression](https://github.com/anomalyco/opencode/blob/b3f1a96c6dd7adeb28b36dd11add1998fc84d67b/packages/core/src/session/compaction.ts): Estimate the entire request, reserve output/buffers, add rolling summaries to recent content, and send toolless summary requests. This implementation defaults to a recent budget of 8000 and a summary output cap of 4096 tokens.
- [OpenCode Overflow Recovery](https://github.com/anomalyco/opencode/blob/b3f1a96c6dd7adeb28b36dd11add1998fc84d67b/packages/core/src/session/runner/llm.ts): Attempt overflow recovery only when assistant output has not yet started, and calls after recovery will not enter the same overflow recovery path again.

ARTEX uses independent output budgets, recent and rolling summaries, and limited recovery. The structured messages and tool matching of norma v0.3.6 are maintained, but Grok's text extraction method is not imported, and OpenCode's main session compression events are not recorded in the ARTEX main transcript.

## Requested Budget and Execution

- The message uses norma's method to estimate UTF-8 bytes for each content block and adds 4/3 margin. Add to this the overhead of system prompts, tool schemas, and message packaging. This estimate is not the exact number of tokens in the model.
- Side question output defaults to a maximum of 8192 tokens, and does not exceed the output limit already set in the main settings. You can set the upper limit of the range 256–32768 with the service environment variable `ARTEX_BTW_MAX_OUTPUT_TOKENS`, and it will not change the product basic model or main operation parameters.
- The input budget is the context window minus the output cap and safety margin, and if the window size is unknown, the platform default of 200K is used. The safety margin is 5% of the window, with a minimum of 128 tokens and a maximum of 8192 tokens.
- Successful questions and answers are retrieved in increasing order, up to 20 sets at a time. The original text leaves up to 20 bundles, and its token budget is within 1/4 of the input budget and does not exceed 16K.
- Questions and answers that exceed the budget are reflected in a rolling summary. The summary includes source notes and context points. Past Assistant answers are not the same as new tool proofs, so if there is a conflict, the most recent main snapshot takes precedence.
- If the main context is still too long, only older messages in the copy are summarized, leaving up to 8K tokens of recent content. The truncation point does not split the tool call and its results. If one batch is too large, put the entire batch into the summary.
- Summary The input is safely divided by UTF-8 according to the actual remaining window size, and the output upper limit is 2048 tokens. Empty summaries, truncated responses, tool calls, and summary budget exceedances are all not written to the cache. There may be a maximum of 12 summary calls in a single side question, all subject to the same 120 second time limit. If the upper limit is reached, it will not repeat infinitely and will clearly end in failure.
- If the model returns a context exceeded for the first time and has not yet emitted text or tool calls, reduce it further and retry at most once. If the estimated size does not decrease, recovery will stop immediately. Other model errors or partially streamed output will not cause this recovery.
- All usage already aggregated, including summaries, failed attempts, and usage at the time of cancellation, is accumulated in the same side question request. If the Provider does not return usage, it is simply recorded as 0, and the estimated value is not disguised as actual usage.

## perpetuation and screen

`side_question_sessions.memory` stores old question and answer summaries, reflected ordinal numbers, and main context summaries cached by snapshot identity. `side_question_requests.context_info` stores preparation steps, number of bundles actually reloaded, summary usage history, and budget estimates.

The summary is only saved when the original request is still running and the cleaned version matches. Purge also clears the cache, and late-arriving writes do not revive data that has already been cleaned up. New snapshots do not reuse summaries from previous snapshots. Summary fields are stored with the v3 working archive, and when restoring an older v3 with missing fields, they are filled with empty objects and v1·v2 remain compatible.

POST accepts and returns requests first, prepares and compacts in the background, and does not hold admission locks or database transactions. The SSE and Record screens display the preparation, Q&A organization, copy compression, and response steps. Compression failures are stored in the failed exit status of the corresponding side query request. The frontend leaves an error and restores a draft of the question that failed this time, and doesn't obscure the input window with a floating notification. Historical polling also no longer clears submission errors.

## Verification record

- Replaying 19, 20, 21, 50 batches, preserving old conclusions beyond 20 batches, reusing summary cache after restart: passing automation.
- Very long Chinese answer and code context, request budget partitioning, tool matching, snapshot immutability, cache invalidation on new snapshots: passing automation.
- Summary Failure·Cancellation·Truncation·Excess length·Tool return, race to empty, call cap, recovery from only one overflow and no retry of some streams: automation passes.
- Page breaks in standalone PostgreSQL, restart, v1·v2·v3 archive, archive restore of summary cache and budget metadata, old v3 with no new fields, 20 parent sessions sharing four concurrent execution spots: Pass.
- Build Go candidate services, check frontend TypeScript, check Biome of modified components, and build Next.js production in independent directory: Passed.
- Using a standalone UI fixture with a built-in browser, we verified the Q&A organizing steps, summary scope guidance, draft recovery after failure, no floating error notifications, no horizontal overflow, and no console errors at 1280×720 and 390×844 resolutions. Temporary fixtures have been removed.
- The new budget check passed when a Worker snapshot already present locally was replayed read-only. For example, the 293085 character snapshot of Worker #3 is no longer incorrectly rejected due to local character counting. There were no external model calls in this item.
- This time, the actual conversation test that attempted to send a private worker snapshot to Grok was rejected by the automatic approval review and was not run, so it is not considered a pass item.
- The local backend was restarted at the user's request at 2026-09-11 00:37, and the original database, data directory, and login settings were used. The SHA-256 of the executable and the candidate binary matched, and the `/api/health` of the backend and frontend proxy both returned OK.

Verification command (using independent test DB only):

```sh
go test -race ./sidequestion ./db ./server -run 'TestSide|TestCheckpoint|TestSnapshot|TestBuildRequest|TestService|TestMainSide|TestTaskArchive' -count=1
go build ./cmd/omniforge
npx tsc --noEmit
npm run build -- --webpack
```

The front-end production build uses an independent copy to avoid overwriting `.next` in the current preview. The candidate service is in `/private/tmp/artex-btw-budget-candidate`, and I copied it to `/private/tmp/artex-btw-preview/artex` and ran it. The original binary was backed up to `artex.before-context-budget` in the same directory.
