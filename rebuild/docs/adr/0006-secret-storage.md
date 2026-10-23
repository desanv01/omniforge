# ADR 0006 — Credential references and reviewed stores

Status: interface selected; store/recovery unimplemented.

Provider/source DTOs hold credential_ref, never secret values. Resolve secrets at
the execution boundary through a reviewed store adapter. Proposed Windows default
is OS credential storage, scoped to the intended user/service identity; verify API,
access behavior and recovery before choosing a library. Headless mode requires a
separately supplied encrypted-store key and explicit backup/recovery plan.

No plaintext file/env fallback, secret probing or migration is implemented. Empty
example configuration does not enable credentials. Legacy dumps may include
plaintext keys; preserve privately and re-enter selected credentials instead of
automatically importing secrets. Logs/errors/events/exports redact values and
secret-bearing headers, URLs and upstream bodies. Encryption at rest alone does
not prove access boundaries or recoverability. Actual store selection, credential
loss/recovery and redaction fixtures remain later work; no ADR can claim them done.
