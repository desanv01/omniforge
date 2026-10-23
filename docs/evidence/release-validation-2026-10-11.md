# Source Distribution Verification — 2026-10-11 (Before Addition of User Guide)

This document is a verification record of a previous release. Please refer to [Verification of subsequent distributions](release-guide-validation-2026-10-11.md) for distributions including usage guides/captures and the latest research fixes.

While maintaining the current functionality, only open sources, documents, and reviewed screens were copied and verified into a separate folder. The existing developer's `.env.local`, `.local-runtime`, DB and logs were not copied. During this process, no new AWS attacks were launched or any cloud resources were changed.

## First-time installation environment

In a separate local Docker Compose project, I ran it like this: LLM-related environment variables were also left blank, so no external model connection was used.

```sh
ARTEX_PROJECT_NAME=aegisloop-release-check \
ARTEX_LOCAL_IMAGE=aegisloop-release-check:20261011 \
ARTEX_LOCAL_PORT=18887 \
ARTEX_LOCAL_PROXY_PORT=18888 \
OPENAI_API_KEY= ANTHROPIC_API_KEY= \
ARTEX_LLM_PROVIDER= ARTEX_LLM_MODEL= \
ARTEX_LLM_BASE_URL= ARTEX_LLM_PROXY= \
./scripts/local-start.sh
```

- The Docker source build and the health check of both ARTEX and PostgreSQL containers passed. The already verified dependency and web build layers used Docker cache.
- I checked `/setup/`'s first administrator password setting screen in the browser. You did not set a password or log in instead.
- The new DB's LLM connection, security log connection, operation, vulnerability, defensive incident, actual loop, and vulnerability investigation records were 0 each.
- Juice Shop, Splunk, and AWS bridge were not created in the default installation.
- The confirmed separate verification container was stopped. The existing app and practice environment were maintained.

![Initial setup screen of distribution source without personal data](images/release-clean-setup-2026-10-11.jpg)

## Check code and visibility

- Passed 27 Windows chain, executor, and bridge regression tests.
- Passed web TypeScript, Biome, and 36 path static builds in the previous implementation verification. In the distribution verification, the same source was built using Docker.
- Basic executable script shell syntax, internal file, image, and anchor references in the document, and space errors were checked.
- A secret detection check was performed on the public text and the existing Git history. The context of the detected test/mock API strings was reviewed to determine whether they were actual authentication information.
- We compared the actual secret value used locally with the publicly available file, and there was no match. Fixed API key strings in older tool usage examples have been replaced with explicit placeholders.
- The new captures are the actual web results and the initial setup screen. I directly checked the screen, which did not contain personal access information or original logs.

The source ZIP does not include `.git` history, actual environment files, keys, AWS/Splunk authentication, DB, original Windows log, original export, or local build output. Includes virtual data for testing and examples of public settings. It also includes new chain execution source, test, log preparation tool, Docker COPY entry, and currently modified files.

`SOURCE_MANIFEST.sha256` records the file list and SHA-256 of the distribution folder (excluding the list file itself). The SHA-256 of the ZIP file is provided separately as the `.zip.sha256` file next to it. This is file integrity verification data and does not mean security authentication.

Actual attack/detection verification is organized separately in [Windows chain records](windows-task-chain-2026-10-11.md). Distinguish between successful source installation and verification of detection quality. For the current scope and upload method, refer to [Deployment Notes](../../RELEASE_NOTES.md).
