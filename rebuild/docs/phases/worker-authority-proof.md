# OF-013-B3C core receiver seam — offline evidence

## Current schema9 source compatibility, actual role proof pending

28 October2026. The worker now requires exactly0009_provider_diagnostics, with no
0008/0009 allowlist. Database, role, of-core-db:5432 endpoint, seven Run UUID scope,
explicit configuration and physical connection policy remain unchanged. Source
compatibility is awaiting independent review and a separately released actual
disposable SQL proof; it is not worker/native runtime readiness or retained cutover.

Startup explicitly denies effective SELECT/INSERT/UPDATE/REFERENCES columns and
DELETE/TRUNCATE/TRIGGER/REFERENCES table privileges on both provider_diagnostics
and provider_diagnostic_rounds. Every required denial is strictly bool false;
missing/null/nonbool/true fails closed with sanitized error and disposal attempt.
The existing three locking-column UPDATE grants remain required and unchanged.

Authority proof now expects twenty application tables plus alembic_version, all
owned by the exact expected owner, and requires nonempty preexisting baselines for
all twenty. Existing SELECT/INSERT/UPDATE grant columns remain unchanged and both
journal tables remain absent from all grants. Effective column privilege checks
cover actual catalog columns; table/column REFERENCES and DELETE/TRUNCATE/TRIGGER
denials include both journal tables. Catalog/schema/constraint/index/function/
trigger digests and row hash multiplicities preserve original data independently
from new seven-Run fixtures and intended role ACL changes. New evidence is named
baseline20; historical baseline18 receipts remain historical and unchanged.

Eight no-row journal probes, rollback-only with exact42501 expected, deny reads,
inserts, updates and deletes on both tables. No destructive TRUNCATE probe or
journal row values are used. First unexpected denial stops later probes/scenarios;
completed probe IDs, active failed probe and partial receiver results remain in
the caller-owned evidence. Seven existing completion/authority/input/cancellation
scenarios remain; synthetic cancellation cleanup grants no normal work or journal
permission and proves no native termination.

Physical worker bounds remain connect3s, pool2/overflow0/checkout1s and server
statement/lock/idle-transaction5000ms. Owner proof transactions independently use
statement5000ms, lock1000ms and idle5000ms; there is no1000ms physical worker-lock
claim. Independent pool inspection/disposal, confirmed-created role NOLOGIN and
twenty-table/schema preservation are attempted after failure/control interruption.
Unknown provisioning/disable commits stay unconfirmed; no reset/reprovision/delete
is performed. NOLOGIN is not session termination and disposal is not service stop.

Fresh disposable CI controller/harness and actual execution remain separately
gated. A proposed fresh trusted job may compare a separately recorded SQL service
identity observation with the proof's second SQL observation, preserving the first
on mismatch. That is two observations in fresh GitHub job provenance, not an
independent retained-volume/control-file or external-capture attestation. Retained
credential-creating authority, migration/cutover, capture/logging/config/channel and
native operations retain their separate gates; external capture remains UNKNOWN.
Journal producers/capability capture/publisher/bridge remain unavailable by default.

Focused source verification passed64 inert tests across worker settings/startup,
authority/projection/denial/failure contracts and journal migration contracts. All
engines, transactions, role/probe calls and receipts were injected; no SQL role,
database, service, secret store or native operation ran. Actual twenty-table
permission/projection/session evidence and controller durability remain unproved.

## Historical schema8 offline seam and preparation

25 October2026. Implemented and fake-tested; frozen for independent review. This
is not role provisioning, database connectivity, Linux receiver execution or native
scheduler readiness.

`infra/core/worker_settings.py` accepts only explicit closed JSON: schema_version1,
database_url and exactly seven distinct canonical Run UUIDs. The fixed driver,
nonowner role, Docker core alias/port and isolated database are validated; URL
options/fallback hosts and artifact/provider/bearer fields reject. No environment
or existing credential discovery is used. Caller supplies an absolute file path;
offline tests inject bytes without reading a real config. DSN is excluded from
repr and validation errors are fixed. The Run allowlist is an application ceiling,
not PostgreSQL row-level isolation or permission to drain pending intents.

`infra/core/worker_db.py` constructs a lazy bounded engine: pool2/nooverflow,
checkout1s/no-preping, connect3s, server statement/lock/idle-in-transaction5s and a
fixed application name. Explicit startup validation checks current/session role,
database/schema/migration0008, nonowner flags/memberships, denied sensitive-table
reads/schema creation and the three required authority-lock UPDATE privileges.
Failure safely disposes the owned engine; there is no bootstrap/migration/fallback.
Effective TEMP is reported, not silently revoked. These startup checks do not
replace the later complete role/PUBLIC/default privilege inspection and live denial
proof. Timeouts are local limits, not guaranteed hard OS termination.

The selected trusted-development role requires actual UPDATE capability on
`case_grants.can_write`, `artifact_associations.revision` and `artifacts.bytes`
because current authority/input checks use FOR SHARE. These are integrity-relevant
mutation permissions. The harmless receiver must never exercise that DML, but a
compromised trusted process could: no read-only authority, hostile containment or
per-Run SQL isolation is claimed. No dummy columns, SECURITY DEFINER functions,
new migration or whole-table UPDATE is introduced. Main's separately reviewed
private privilege matrix governs any future provisioning.

One offline run passed **15 tests**,0failures/errors/skips, runner0.015s (unittest
reported0.023s on the platform clock). Tests cover exact closed schema/types,
duplicate/size/encoding errors, redaction, path rejection/no ambient discovery,
seven-Run membership, origin/role/options denial, lazy constructor bounds, explicit
startup success, identity/owner/flag/migration/read-privilege failures, missing
locking privileges, TEMP reporting, safe construction/connect/query/disposal
failures and revalidation of a bypass-mutated frozen settings object. All readers,
engine constructors and connections were injected fakes. No actual PostgreSQL
connection, role/password/config write/read, network/runtime or SDK worker launch
occurred. No dependency/install/accepted-suite repetition was needed.

Native receiver SDK construction remains a separate owned seam. This core helper
does not supply Hatchet tokens, workflow registration, child-process ownership or
transport. Actual role grants/denials, private config ACL/UID readability, eighteen-
table history preservation, Docker namespace connectivity and native seven-case
execution remain separately authorized gates. Independent review and Main's
intended-head CI/delivery are required before acceptance of these five files.

## B review corrections — explicit-input boundaries

The initial15-test evidence above is preserved. B identified two concrete gaps:
an explicit SQLAlchemy URL alone did not block libpq ambient PG connection settings,
and accepting either POSIX or Windows absolute syntax could become a relative
path on the other host. Both were corrected within the same five-file slice.

A SQLAlchemy creator now checks PG-prefixed environment variable NAMES before
every physical DBAPI connection, including later reconnects after lazy construction.
Any such setting fails closed with a fixed error before driver invocation; values
are not read/logged and process environment is not changed. Clean connections pass
explicit host/port/database/user/password and the fixed timeout/application policy.
TLS, GSS encryption and channel binding are explicitly disabled for the selected
trusted-development internal topology; passfile is the host null device, not a
discovered user file. No service/hostaddr/credential-file fallback is supplied.
This is not production TLS or a native connectivity proof. Concurrent untrusted
process-environment mutation is outside the trusted in-process launch boundary.

The file loader now requires the actual host Path.is_absolute result before its
reader, rejecting foreign relative spellings and both UNC/device variants. It does
not reinterpret another OS's absolute syntax or choose a drive/current directory.

One focused correction run passed9 tests,0failures/errors/skips, runner0.015s
(unittest0.012s): five new PG-environment/host-path cases plus four directly affected
existing reader/constructor cases. PGHOSTADDR/PGSERVICE/TLS/options/passfile denial,
clean explicit parameters, environment changes between physical connects, name-only
inspection/no mutation and rejected-before-read host paths were verified with fakes.
No actual DBAPI call/config read/env mutation occurred. The original15 aggregate
was not repeated; the final20-case module discovery remains for intended-head CI.
Independent B delta review and Main delivery remain required.

## Actual role proof source — PREPARED / UNEXECUTED

`tests/integration/core/worker_authority.py` prepares a separate, explicitly released
actual PostgreSQL role proof. Importing it performs no I/O; it has no CLI or discovery
path. Static AST inspection only has been performed. No actual role, password,
config, database, native scheduler or network operation has been executed for this
preparation. Independent review and Main's bounded execution release remain required.

The complete SELECT/INSERT/UPDATE column matrix and generated non-secret GRANT SQL
are in that module. It grants no table-wide/future-column permissions. The candidate
is the accepted trusted development receiver: nonowner LOGIN, NOINHERIT,
NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS, connection limit four.
UPDATE of case_grants.can_write, artifact_associations.revision and artifacts.bytes
is real mutation authority required for PostgreSQL FOR SHARE; this is not SQL or
per-Run isolation. Receiver code must remain trusted. Shared PUBLIC grants are never
revoked. Effective privileges are checked against every extant public table column;
PUBLIC/default ACLs, TEMP and executable function metadata are reported separately.

The future proof creates exactly seven fresh additive synthetic Runs, each with its
own principal, case, grant and metadata-only input. Purposes are completion, cleanup
after grant revocation, revoked-grant admission, changed-input admission, wrong
registration payload, stale renewal and wrong registration context. These are a
separate ledger from any later seven native-case Runs. Positive register/admit/renew/
complete/cleanup calls use actual nonowner connections and injected observations;
they prove no native execution or OS termination. Denial queries use WHERE false or
transactional DDL rolled back even on unexpected success; sensitive rows are never
returned, and no old row is intentionally mutated. No pending queue scan occurs.

Future invocation is `execute(owner_engine=..., expected_owner=...,
expected_cluster=..., new_secret=..., release=RELEASE, evidence=evidence)` from this module in the
Backend-owned proof process. All values must come through the separately approved
private runtime channel. It checks exact database/schema, cluster system identifier,
database/table ownership, expected resources and role absence before provisioning.
An existing role is never reset. The exclusive owner engine must have echo disabled,
hidden parameters and bounded connection timeouts. Every owner transaction sets
bounded statement/lock/idle timeouts. Accepted receiver construction retains the
literal of-core-db:5432 endpoint and PG-environment rejection; no host fallback or
SET ROLE substitutes for an actual receiver login.

Required before that call: independent source review, exclusive isolated core
runtime window, verified resource/cluster identity, approved endpoint resolution,
fresh synthetic secret delivery and PostgreSQL password-log controls. The proof
does not read or write a credential/config file or mount owner credentials into a
receiver. Caller owns private receipt persistence and supplied secret retirement.
The caller-owned evidence must be retained even on failure or interruption. It records preservation of
all original row projection multisets across eighteen tables, catalog structure,
seven proof identities/purposes, denials and receiver checks, pool settlement and
role disposition. Finalization retains the new role NOLOGIN with grants/history;
failed or uncertain provisioning/disable is reported for Main action. No rows,
roles or resources are silently deleted, no database stop is implied, and actual
runtime/config/native execution gates remain separate.

### Interruption protocol correction — PREPARED / UNEXECUTED

The caller must allocate an empty plain `evidence` dict before invoking `execute`
and persist that same dict to the approved private receipt destination in its own
`finally`, whether the call returns or raises any BaseException. The caller must
catch `ProofInterrupted` at its outer control boundary, retain its `.report` (the
same dict), and propagate a fixed interrupted outcome to Main without printing a
traceback, exception locals, SQL parameters, DSN or secret. Ordinary operation
errors also produce only fixed failure-stage labels. No control interruption can
produce a passing outcome. The caller must implement receipt persistence before
any separately released actual invocation; this source writes no receipt/config.

The body and each settlement stage catch BaseException separately. Receiver pool
inspection and disposal, confirmed-created role NOLOGIN, baseline/schema
verification, and owner pool inspection and disposal are independent attempts.
An interruption in one attempt records a sanitized interrupted state and allows
the subsequent attempts to run; after settlement a sanitized ProofInterrupted
propagates with the evidence. No automatic retry or resource reset is added.
Provisioning and NOLOGIN commit states become unconfirmed before their respective
transactions and confirmed only after successful transaction exit. An uncertain
creation is reported for Main inspection rather than altering a possibly existing
role. The seven-Run ledger is recorded before provisioning commit and baseline
evidence is recorded before provisioning begins. Interrupted pool construction or
disposal stays explicitly unconfirmed; disposal never claims physical connection
termination, and NOLOGIN never claims existing sessions were terminated.

These are Python control-exception boundaries, not a guarantee against repeated
asynchronous interruption between instructions, hard kill or process/host loss.
The caller's outer runtime controller must retain whatever private evidence is
available, inspect unconfirmed resources and report unresolved disposition to Main.
No actual role/runtime operation or fake runtime test has been performed by this
source-only correction. Independent C delta review remains required.
