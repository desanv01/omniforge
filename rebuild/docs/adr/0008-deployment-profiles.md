# ADR 0008 — Local browser-first profiles

Status: minimal local API verified separately; broader profiles proposed.

Core profile: browser/API, independent PostgreSQL, external artifact storage and
explicit provider configuration. Execution adds scheduler and isolated workers.
Research adds only individually justified lab/search/inference services. No blanket
catalog installations. No Vercel/cloud provisioning or public release is selected.

The scaffold serves health only, defaults to documented loopback invocation and
does not auto-connect dependencies. Data and credentials stay outside source;
new ports/DB/Compose/storage names must be selected against actual local state by
the assigned runtime owner. Never repurpose the legacy resources. Native core is
possible; arbitrary tools still need approved isolation. Browser-first delivery
avoids a premature desktop IPC/installer layer. OF-011 proves one browser/API/DB
transaction; Phase11 owns installation, backup/recovery and representative resource
measurements. Legacy recovery acceptance is limited and does not prove new-stack
or full historical-installation recovery.
