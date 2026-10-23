# ADR 0007 — Portable manifest and human report

Status: contract direction selected; schema/round trip pending OF-014.

Use a versioned JSON manifest plus Markdown report and immutable content-addressed
relative files. Include originals, derivations, exact evidence locations, claims,
coverage, legacy envelopes and source/migration provenance. Verify hashes and sizes
before publication. Reject traversal, absolute/private host paths and symlinks.
Exports exclude secrets; credential_ref is only a nonsecret identifier subject to
publication policy. Raw evidence still requires sensitivity review.

JSON alone is readable but loses binary originals; a report alone loses machine
provenance. A vendor-specific database dump is not the portable case format.
OF-014 owns fixture schemas and deterministic malformed/truncated/duplicate-origin
round trips. Actual legacy migration reconciles all observed tables and files in
Phase12; optional or unsupported entities remain preserved, never silently dropped.
