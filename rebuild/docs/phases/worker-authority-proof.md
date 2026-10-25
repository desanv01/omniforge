# OF-013-B3C core receiver seam — offline evidence

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
