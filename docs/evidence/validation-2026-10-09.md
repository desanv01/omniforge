# Source distribution verification record · 2026-10-09

The verified application source commit is `3379aa1`. This document and the initial installation capture added later record the verification results. Rather than copying the existing development environment, I cloned the corresponding Git commit into a separate folder as `git clone --no-local`.

## new installation

In Docker Desktop's Linux ARM64 environment, existing apps, projects, images, and ports were separated as follows. LLM provider-specific environment variables are left blank.

```sh
ARTEX_PROJECT_NAME=artex-release-check \
ARTEX_LOCAL_IMAGE=artex-release-check:dev \
ARTEX_LOCAL_PORT=18887 \
ARTEX_LOCAL_PROXY_PORT=18888 \
./scripts/local-start.sh
```

| Check items | Actual Results |
|---|---|
| Operating files immediately after clone | `.env.local`, `.local-runtime/`, `data/`, `evidence-local/` None |
| Basic service | Start with only 2 ARTEX and PostgreSQL, all healthy |
| App·Proxy Port | `127.0.0.1:18887`, `127.0.0.1:18888` |
| Authentication initialization status | `initialized: false` of `/api/auth/status` |
| Previous record | 0 each for tasks, vulnerabilities, Splunk connections, and breach investigations |
| Home screen | New administrator password setup screen; [Actual Capture](images/05-clean-install.png) |
| external execution | No actual LLM/Splunk call or vulnerability check execution |

Juice Shop was not used to verify this installation. The other [practice capture](README.md) was obtained from an existing lab environment that was run separately.

## tests run

| inspection | Results and Scope |
|---|---|
| `ARTEX_TEST_PROJECT_NAME=artex-release-test ./scripts/local-test.sh` | Top 150 tests passed on new clone; Separate temporary PostgreSQL, mock LLM·TLS using Splunk |
| `go test ./... -count=1` | Passed DB-free test of entire package; Check the DB integration path through the separate check above |
| `go vet ./...` | passed |
| `npm run build:static` | Pass static web build·TypeScript inspection |
| `npm run check` | Passed without error; 126 existing warnings and 747 pieces of information remain |
| `python3 -I scripts/check-web-cjk.py` | 0 Chinese character leaks in 32 generated HTML |
| `python3 -I scripts/check-doc-links.py` | Pass internal link·image·anchor inspection in document |

General Go tests were run in a temporary container that blocked the external network and did not convey the operational DB/host environment. Passing the test does not demonstrate actual breach detection accuracy or compatibility with all provider or operational SIEMs.

## Excluding confidential and operational data

- Past Git history, including deployment candidates and upstream, was reviewed using Gitleaks 8.30.1 and separate key, private key, and JWT pattern checks. None were confirmed to be actual usable credentials.
- The 5 candidates and 8 histories from Gitleaks basic rules were synthetic strings from masking tests and authentication examples from past UI demos. This is not the result of passing the entire file as an exception or ignoring scanner errors.
- Staging checks for new deployment changes resulted in 0 Gitleaks findings.
- Environment files, JWT keys, operational DB/dump, upload source log, and overall result export are not included in Git. Reflected exclusion rules in `.gitignore` and both Docker build exclusion files.
- Five public images were visually inspected separately. It does not include the entire API key setup screen, administrator password, connection credentials, or original logs.

This does not mean that the scanner will detect all secrets or automatically inspect image pixels. Existing developer secrets and data are kept locally and separated from the distribution source.
