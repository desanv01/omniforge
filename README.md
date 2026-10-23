<div align="center">

# OmniForge

**AI-assisted security testing, incident investigation, and detection validation**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Backend](https://github.com/desanv01/omniforge/actions/workflows/ci.yml/badge.svg)](https://github.com/desanv01/omniforge/actions/workflows/ci.yml)
[![Frontend](https://github.com/desanv01/omniforge/actions/workflows/web.yml/badge.svg)](https://github.com/desanv01/omniforge/actions/workflows/web.yml)

[Quick start](#quick-start) · [Features](#features) · [Development](#development) · [Documentation](#documentation)

</div>

OmniForge brings vulnerability testing, evidence-based incident investigation, and detection rule evaluation into one web application. It uses a Go backend, a statically exported Next.js interface, and PostgreSQL. English is the default interface and agent response language.

This independent repository continues the work of [ARTEX](https://github.com/Autumn-27/ARTEX), [artex-ko](https://github.com/jiwoochris/artex-ko), and the artex-ko-plus/AegisLoop extension. Their authorship, source history, and AGPL-3.0 license are retained.

## Features

| Area | Workflow | Output |
|---|---|---|
| Overview | Navigate testing, investigations, and detection evaluation | Saved work and activity summaries |
| Offensive | Run agent-assisted tests against authorized targets | Findings, assets, traffic, and reproduction evidence |
| Defensive | Import files or query Splunk, prepare evidence, then start an investigation | Timelines, hypotheses, queries, and evidence exports |
| Closed-loop | Revalidate a finding, collect evidence, compare baseline and candidate rules | Per-run detection results and rule revision history |
| Offline evaluation | Separate labeled improvement and evaluation datasets | TP/FP/TN/FN, precision, recall, and false positive counts |
| Optional lab | Exercise a dedicated Windows/Splunk lab | Reproducible samples and traceable evaluation artifacts |

Evidence preparation and deterministic rule evaluation can run without an LLM. Agent-driven testing and AI investigation require a configured model provider. Investigation excerpts are sent to that provider when those features are used. Run active security tests only against systems you are authorized to assess.

Shadow rule matching does not deploy production SIEM rules or blocking policies. The optional lab integration has a separate, explicitly configured path for its dedicated Splunk rules. Historical sample results do not establish general detection accuracy or operational performance.

## Screenshots

The screenshots below document the inherited AegisLoop interface and historical lab data. They predate OmniForge's English conversion; a fresh installation does not contain those records.

![Inherited overview](docs/evidence/images/aegisloop-overview-2026-10-11.jpg)
![Inherited incident investigation](docs/evidence/images/aegisloop-defensive-2026-10-11.jpg)

## Quick start

Install Docker Desktop with Linux containers, or Docker Engine with Compose v2. Git Bash or WSL provides the shell used by the startup helper on Windows.

```sh
git clone https://github.com/desanv01/omniforge.git
cd omniforge
sh scripts/local-start.sh
```

Open [http://localhost:8787](http://localhost:8787). Complete the first-run password setup, then sign in as **OmniForge**. Configure your model provider in Settings before starting an AI task. The legacy `ARTEX` login remains accepted for existing installations.

The helper generates a database password in `.env.local` and a signing key in `.local-runtime/jwt.key` only when those files do not exist. Keep those files and the PostgreSQL volume when upgrading. App data is stored in `data/` and the database volume; runtime credentials and data are excluded from Git. The web port and proxy port bind to localhost by default.

Optional provider environment settings are documented in [.env.example](.env.example). Existing `ARTEX_*` environment names and the `artex-local` Compose project name remain compatible so an upgrade uses the same data volume.

To stop the local services while retaining data:

```sh
docker compose --env-file .env.local -f docker-compose.local.yml stop
```

To rebuild after updating the source, run `sh scripts/local-start.sh` again.

## How it works

1. The Next.js application is exported as static files and embedded in the Go executable.
2. The Go HTTP server serves the interface and authenticated JSON API.
3. The agent engine manages tasks, tools, model calls, and event streams.
4. PostgreSQL stores tasks, evidence, findings, and investigation state.
5. File and Splunk adapters supply evidence for investigations and rule comparisons.

The optional recording proxy listens on port 8788. Installing its certificate and directing traffic through it are separate setup steps; starting the application does not intercept your normal browser traffic.

## Development

Use the Go version in [go.mod](go.mod), Node.js 22, and PostgreSQL 16. The Docker source build supplies these toolchains for normal local startup.

```sh
# Frontend dependencies and production static export
cd web
npm ci
npm run build:static
node ../scripts/check-english-locale.mjs
npm audit
cd ..

# Backend compilation and documentation integrity
go build ./...
python3 scripts/check-doc-links.py

# Focused integration suite with an isolated disposable database
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f docker-compose.test.yml down
```

For a packaged executable with embedded frontend assets, `./build.sh --target linux/amd64 --no-compress` builds `dist/omniforge-linux-amd64/omniforge`. The build script also supports release archives; `ARTEX_*` build variables are retained for compatibility. Runtime Docker images are built from [Dockerfile.local](Dockerfile.local); the separate [Dockerfile](Dockerfile) accepts a prebuilt executable under `dist/<arch>/omniforge`.

GitHub Actions checks the backend, frontend, dependency advisories, and internal documentation links. Release and lab workflows are manual. In-app update checks point to **desanv01/omniforge**; they report that no release exists until this repository publishes one.

## Project layout

| Path | Purpose |
|---|---|
| `cmd/omniforge/` | Backend entry point and startup lifecycle |
| `server/` | HTTP API, authentication, and embedded interface |
| `agent/`, `engine/`, `tools/` | Agent execution, scheduling, and tool integrations |
| `db/`, `config/` | Persistence and configuration |
| `investigation/`, `securitysource/` | Incident evidence and source adapters |
| `closedloop/`, `defenseeval/` | Revalidation and detection evaluation |
| `web/` | Next.js frontend and English message catalog |
| `scripts/`, `.github/` | Startup helpers, checks, and CI workflows |
| `skills/`, `docs/` | Agent capabilities and project documentation |

## Documentation

- [User guide](docs/USER_GUIDE_KO.md) — English guide; its filename is retained for existing links.
- [Workflows, APIs, and limitations](docs/aegisloop.md).
- [Architecture and source analysis](docs/aegisloop-source-analysis.md).
- [Optional Windows/Splunk lab](docs/aws-windows-loop.md).
- [Historical evidence and scope](docs/evidence/README.md).
- [Upstream English reference](README.en.md) and [Chinese reference](README.zh.md).

The primary documentation and default application experience are English. Original Korean and Chinese message catalogs and selected historical documents remain available as reference material. Source comments and original evidence may retain their original language.

## License and attribution

OmniForge is distributed under [GNU AGPL-3.0](LICENSE). Original ARTEX, artex-ko, and artex-ko-plus notices and history remain part of this project. Rebranding does not change those license obligations. Third-party packages retain their own licenses.
