# OF-014 — portable evidence and original capture provenance

24 October2026. Implemented prototype awaiting independent review. No legacy
database import, provider call, scheduler integration or publication is claimed.

## Concrete format and behavior

`packages/contracts/export/manifest.schema.json` and executable strict models
describe v1. Directory bundles contain manifest.json, deterministic report.md and
only declared `blobs/<sha256>` originals/derivations. A bundle carries stable case,
artifact and distinct origin association/source IDs; capture/import timestamps;
source/schema/revision/migration provenance; exact evidence locations; coverage-
qualified observations; cited interpretations; derivations; and limited preserved
legacy-state envelopes. Original raw legacy configuration/credentials are not
automatically included. Unknown source metadata remains null/unknown.

The original capture timestamp text and offset token now survive separately from
the normalized UTC instant. API/upload and portable model use the same CaptureTime
semantics. Migration0002_capture preserves all existing capture instants and marks
their original representation/offset unknown; it does not infer timezone from a
database session. New input supports RFC3339 with explicit offset, uppercaseT/Z,
and at most six fractional digits; invalid dates, absent offsets, >6 fractional
digits and invalid offset fields are rejected rather than silently rounded.
The -00:00 token is preserved as unknown local-offset declaration, not a known
historical source timezone. Portable imported_at is timezone-aware and retained;
there is no replacement with the current import/roundtrip time.

Byte selectors use zero-based half-open bounds. Line selectors use one-based
inclusive LF-delimited UTF8 lines; raw CRLF and terminators remain in returned
bytes. Binary byte ranges do not normalize text. Each citation ties hash plus
origin association to exact bytes. Observation source IDs must match the source
of every cited location; identical bytes from another source do not confer
provenance. Verified interpretation states require citations. A complete-empty
collection can declare not_observed; incomplete/unknown-empty cannot become a
clean negative. These coverage/source declarations do not authenticate collection.

The bounded prototype rejects malformed/truncated manifest JSON, duplicate JSON
keys/nonfinite values, unknown fields/references, conflicting identities, unsafe
relative paths, absolute/private-path metadata shapes, symlinks/Windows reparse
points, nonregular files, wrong directory nodes, size/hash mismatches and invalid
citation bounds/UTF8. Strict integers reject bool/string/float selectors and counts.
JSON/CSV parser fixtures separately reject malformed/truncated syntax; malformed
original bytes can still be preserved as evidence without claiming successful
parse or a negative finding. Parser failure never returns an empty success.

Limits: manifest/report1MiB, file25MiB, aggregate64MiB, at most64 artifact blobs,
128 origins/observations/claims,256 locations. CSV parsing bounds10000rows,
256columns and65536characters per field. No archive/ZIP extraction is provided.
Regular-file guards precede file opening; bundles must be quiescent, privately
controlled directories while validating. Concurrent hostile filesystem mutation
is not proven safe by a separate lstat/open check. Reads are size bounded;
partial output remains visible and no originals, stages or failed outputs are
deleted. Repeated same-manifest export verifies existing identical content;
conflicts fail without overwriting. Import is model validation/loading and
directory round trip, not insertion into the application database.

## Privacy and schema limits

Bundles include explicitly selected original evidence and stay private/sensitive
unless separately reviewed for sharing. Only authored synthetic fixture bundles
were verified secret/private-path free. Metadata checking rejects obvious labeled
credential/private-path shapes but is not a secret scrubber; opaque secrets may
have no detectable label, and original blob contents are intentionally unscanned.
No automatic classification/public-sharing claim follows from validation. Export
does not carry case grants, bearer tokens, provider secret values or credential
store records. Actual source sensitivity/publication policy remains a later gate.

Generated JSON Schemas express structural types/bounds. Python model and filesystem
validators additionally enforce cross-entity/source/hash/path/capture and coverage
invariants; validating JSON Schema alone is insufficient. Markdown links only
canonical content paths and escaped text; no user-controlled active HTML/link is
needed for evidence access. Hash establishes byte identity, not authenticity.

## Reproduce selected offline prototype

Use the existing locked Python environment. No new dependency was added.

```powershell
python -m packages.contracts.export.generate
python -m tests.fixtures.evidence.build_fixture
$env:OMNIFORGE_EVIDENCE_PROOF_ROOT = '<private-test-output-root>'
python -m tests.contracts.evidence.check
python -m packages.contracts.export validate <selected-private-bundle>
python -m packages.contracts.export roundtrip <selected-private-bundle> <private-copy>
```

Tests retain generated synthetic outputs for review; actual junction/reparse
creation on Windows may need the approved nonsandbox background route. Windows
does not expose POSIX FIFOs through this fixture, so the FIFO stat/no-open guard is
tested with synthetic stat metadata plus an actual directory-as-manifest node;
POSIX runs create a real FIFO and reject before opening. Real Windows junction
rejection was observed, with its target unchanged/empty.

Ten unique offline tests passed across the final recorded run and one targeted
fixture correction. Nine passed in the structured10-test run; the escaping fixture
was corrected to use an accepted text shape because its closing HTML slash was
conservatively rejected as an absolute path. Only that test reran and passed.
Earlier raw terminal output was incomplete, so final acceptance evidence uses
private structured receipts; an incomplete exit is not counted as a passing suite.
No broad unchanged revalidation followed the correction.

Focused actual retained-PostgreSQL evidence: migration0002 preserved all8 prior
association rows/capture instants and marked original offsets/text unknown; a
new+05:30 timestamp upload/persisted read returned normalized07:04:56.123456Z plus
the exact12:34:56.123456+05:30 original. Fresh-grant authority seam and HTTP range
returned exact bytes, rejected hash mismatch and denied after grant revocation.
Affected health/OpenAPI and new capture/seam tests passed (2tests), client was
regenerated from implemented API and strict TypeScript compile passed.

## Shared ownership and pending work

Provider callable `bind_read_range(engine,root,principal,case)` binds trusted
application identity, not model arguments; every read checks fresh grant, origin,
publication, expected fullblob hash, size and exact range. Finite OF-012I will
exercise the accepted deterministic provider through this seam separately; this
document does not claim that integration result. Scheduler core Run/Event/Attempt/
outbox migration and router integration remain separately assigned requests.

The accepted browser proof used frozen migration0001 before these changes; it was
released before API cancellation and migration0002. Additive generated fields were
announced to UI/provider owners; frontend rebuild against new contract is owned
by UI. Portable proof is not full migration/cutover, hostile-parser isolation,
power-loss recovery, sustained-ingestion quota/cleanup or a production installer.
No legacy resources, credentials, source history or original evidence were removed.
