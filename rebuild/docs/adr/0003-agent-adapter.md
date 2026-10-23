# ADR 0003 — Application-owned read-only provider contract

Status: boundary selected; Pydantic AI remains candidate pending OF-012.

Own answer(ReadOnlyContext, ProviderProfileRef, Budget) independently of an SDK.
Results contain typed observations/claims/citations and nullable usage with
provenance. Pin profile endpoint/model; no silent failover. Tools enforce grants,
bounds, cancellation and budgets outside model instructions. The initial tool is
read_evidence_range. Evidence text cannot grant execution rights.

Pydantic AI is proposed for typed output/tools but is not installed, locked or
claimed compatible in this slice. A small direct HTTP adapter is the fallback if
its measured fit fails; do not add multiple frameworks speculatively. OF-012 owns
version selection, mock fixtures, independent schema/stream/tools capability
checks, and separately bounded DeepSeek round trip when credentials are configured.
No mock result proves live-provider behavior. Provider-hosted search is separate.
