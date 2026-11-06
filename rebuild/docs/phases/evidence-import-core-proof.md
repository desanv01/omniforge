# Phase2 bounded import core

6 November2026. OF-P02-IMPORT-CORE-A implements a pure callable for supplied byte
chunks in `services/api/import_core.py`. This isolated Phase2 boundary is ready
for independent source/test review. Integrated Phase2 acceptance and Phase1 parent
completion remain separate. No HTTP route, database/schema/migration, durable
publication, filesystem write or import/export round-trip is added.

## Calling and limits

```python
from uuid import UUID
from services.api.import_core import ImportLimits, import_chunks

result = import_chunks(
    (b"name,value\n", b"sample,001\n"),
    logical_name="sources/sample.csv",
    media_type="text/csv; charset=utf-8",
    association_id=UUID("d47884cf-207a-4052-b6b9-87e9a8c54445"),
    limits=ImportLimits(max_bytes=65536, max_output_bytes=131072),
)
```

Input and output byte limits are mandatory positive integers, each at most25MiB
to match the existing Artifact model. Booleans are rejected. Other defaults/hard
ceilings are: chunks4096/65536, CSV data rows10000/100000, columns256/1024,
field characters65536/65536, JSON nesting64/64, JSON lexical tokens20000/100000
and numeric token characters256/256. Limits are revalidated on entry, including
forged frozen dataclass values. Empty chunks count toward the chunk budget.

The callable checks byte/chunk budgets while consuming the iterator and stops
advancing it immediately on rejection. Only exact immutable bytes chunks are
accepted; a raw bytes/string/buffer is not a chunk iterable for this API. Successful
results retain all original bytes and SHA256 computed over their exact sequence.
Parsing uses the complete bounded decoded document. This is bounded streaming
intake with buffering, not a constant-memory parser or a wall-time guarantee for
a caller's arbitrary iterator. The caller owns source retention and producer
lifecycle; the callable performs no automatic close/rewind/retry or storage.

## Names, formats and encoding

Logical names are1–255 characters, relative forward-slash paths with nonempty
segments. Accepted segment characters are Unicode letters/marks/numbers and ASCII
spaces/dots/underscores/hyphens. Names must already be NFKC-normalized. Traversal,
absolute/drive/UNC paths, backslashes or mixed separators, control/format characters,
percent escapes, Windows device basenames and trailing dots/spaces reject. No name
is interpreted as a filesystem destination. `original_name` gives the basename
for later association metadata; the full logical name stays in the result.

The closed MIME set is text/plain, application/json and text/csv, with optional
UTF-8 charset only. MIME case is normalized; control characters and other
parameters/encodings reject. Extensions must match: .txt/.log, .json or .csv.
There is no content guessing, binary fallback, archive/HTML/document parser,
network retrieval or credential operation. HTML-looking content declared plain
text remains uninterpreted text; this slice performs no rendering.

All formats use strict UTF-8. A single leading UTF-8 BOM remains in original
bytes/hash and is removed only from extraction. Incremental decoding supports
splits within BOM/multibyte sequences. Invalid bytes and truncated final sequences
produce numeric original-byte offsets. There is no newline or Unicode content
normalization.

Plain text retains decoded content verbatim in UTF-8. C0/C1/DEL control characters
other than tab/CR/LF reject. Empty text is valid and has zero records and no invented
nonempty byte citation; other text counts as one document record.

JSON accepts exactly one complete standard JSON value, including scalars. It
rejects duplicate decoded object keys, NaN/Infinity, trailing values, malformed or
truncated syntax and unpaired Unicode surrogates. A lexical prepass enforces
nesting/token budgets before allocating the JSON tree; keys count as tokens too.
Numbers are validated as bounded lexical tokens without integer/float conversion,
so large/precise values and exponent spelling are not rounded or retyped. Validated
JSON text is retained verbatim in extracted UTF-8, apart from the optional BOM.
This API returns bytes, not a parsed number-coerced object. JSON counts as one
document record; collection coverage is not inferred.

CSV uses Python's strict excel dialect: comma delimiter, double-quoted cells and
double-quote escaping, LF/CRLF and quoted embedded newlines. The first record is
a nonempty header with unique nonempty exact column names; case/whitespace are
preserved. Each following record must have exactly that width; blank records are
not silently dropped. Cells remain strings, including numeric-looking values and
formula-looking content. No type/formula interpretation occurs. Unsupported
control characters reject. Malformed/truncated quoting and the stdlib field-size
guard produce actionable CSV errors; this function never changes the process-wide
csv.field_size_limit. Explicit column/field/row limits also apply. Extraction is
compact UTF-8 JSON `{ "columns": [...], "rows": [[...], ...] }`, bounded while
encoding by max_output_bytes. CSV record_count excludes the header.

## Identity, immutability and lineage

An optional tuple of at most64 existing Artifact models is revalidated and copied
into a local identity snapshot. Duplicate SHA/IDs, malformed models and byte-count
conflicts reject. A verified duplicate reuses its existing artifact UUID even under
a different logical name, with is_duplicate=true. It still undergoes full decoding
and format validation; known identity cannot bypass malformed-input checks. New
content identities use deterministic UUID5 names bound to SHA256; conflicting
known UUIDs reject. The supplied registry/models are never changed or registered
as a side effect.

ImportResult and its ArtifactRef, ExtractionLineage and ByteOrigin are frozen;
original/extracted payloads are bytes. `to_model()` produces fresh existing
Artifact/Derivation/Location DTOs, so changing a returned mutable DTO cannot change
the stored result. Extraction lineage binds original/output identities and hashes,
tool version and exact policy/limits options SHA256. Tool version is captured in
the immutable lineage. Changed versions or reused external artifact IDs produce
distinct lineage identities. Whole-input byte locations use the caller-supplied
association UUID and original hash with half-open0..length bounds. Empty originals
have no nonempty Location. No capture/import timestamp or source provenance is
invented; association authority/provenance remains the caller's responsibility.

Complete lineage coverage means complete extraction of this supplied supported
document, not complete source-system collection or evidence of a negative. Text
or JSON extraction may have identical bytes and therefore the same input/output
artifact identity: this is a validation/identity derivation, not another blob.
Consumers must deduplicate content-addressed artifact references. Full association,
portable manifest/private-metadata checks and durable round-trip are later gates.
Annotations remain outside this slice.

ImportFailure supplies a fixed actionable code/message and optional numeric
byte_offset or line/column. Codes distinguish stream/byte/chunk/encoding errors,
unsafe names/MIME mismatch, JSON syntax/duplicate/depth/token/number errors, CSV
header/width/field/row errors and identity/output conflicts. No raw input or source
exception text is interpolated into errors. The callable emits only one complete
successful result or raises; it has no output sink, partial-result yield or
publication callback. A failure may consume source chunks through the rejection
point, but cannot mutate their bytes or the caller's identity snapshot.

## Actual bounded verification and remaining gates

Pinned Python3.11 environment, `-B -m unittest -f
tests.contracts.evidence.test_import_core`: all17 new tests passed. Later lineage
version/reference hardening was checked with focused lineage tests and a final
run of the same new17-test module; no existing accepted suite reran. The tests call
the actual importer with small in-memory data, including byte-by-byte CSV/BOM,
every two-chunk multibyte split, early consumption stop, pathological empty chunks,
malformed/truncated formats, duplicates/conflicts, immutable DTO lineage and
absence of partial successful results. Filesystem/network/process entrypoints
are blocked in the callable's no-I/O check. No DB, migration, service, provider,
credential store, project native process, install or runtime operation executed.

Independent C review and Main's Git/CI delivery remain required. Durable artifact
storage, HTTP/API/UI integration, annotations, complex-document parsing, capture
provenance reconciliation, full import/export round-trip and integrated Phase2
and Phase1 acceptance remain unexecuted here.
