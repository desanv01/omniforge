# ADR 0002 — Immutable evidence with distinct origin associations

Status: selected contract direction; storage/recovery proof pending OF-011/014.

Store immutable artifact bytes by SHA256 outside source. DB records cases, source
associations, evidence locations, derivations, observations and claims separately.
Identical bytes do not merge origins or grants. Byte identity is not authenticity.
Capture time may be unknown; imported_at cannot fill it. A claim must reference
resolvable locations and retain uncertainty/coverage. Legacy result and lifecycle
vocabularies survive in provenance envelopes without strengthening assertions.

Use PostgreSQL as proposed metadata store, local files as proposed blob store.
Neither is connected in OF-010. Explicit publication state and reconciliation are
required because filesystem and DB writes cannot be one atomic transaction.
Alternatives: embedding every blob in DB simplifies transactionality but changes
backup/size costs; object storage adds service ownership and is deferred. Exact
range/hash, duplicate associations, malformed inputs and crash windows must be
proven before this design is accepted as a working evidence core.
