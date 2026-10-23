# Contributing Guide

Korean · [English](CONTRIBUTING.en.md)

Thank you for your interest in ARTEX Korean version (`artex-ko`). Before you start contributing to this document
This is a summary of the scope, policies, and procedures you need to know in Korean. Before sending your contribution, be sure to
Please read [Scope of Use and Legal Responsibilities](#scope-of-use-and-legal-responsibility) and [Localization Policy](#localization-policy) first.

- To report a bug or suggest a feature → use [Issue Template](https://github.com/jiwoochris/artex-ko/issues/new/choose).
- If you find a translation/localization error → Use the “Translation/Localization Error” issue template.
- If you discover a security vulnerability → **Do not raise it as a public issue** but follow the procedure in [SECURITY.md](SECURITY.md).
- All participants must adhere to the [Code of Conduct (CODE_OF_CONDUCT.md)](CODE_OF_CONDUCT.md).

---

## Scope of use and legal responsibility

ARTEX is an offensive security tool that allows LLM multi-agents to **autonomously** perform penetration testing.
Contributors are subject to the same scope restrictions as users.

- You may verify code only if you own it or have express written permission to do so.**
  **Local isolation environment** (e.g. OWASP Juice Shop/DVWA launched with Docker, intentionally vulnerable and
  Run the tool only on targets you own.
- Code that performs scanning, detection, or exploitation of unlicensed physical, operational, or remote systems;
  or any changes that would encourage such use.
- In Korea, an act of intruding into or causing a disruption to another person's information and communications network without permission is prohibited.
  It is a violation of the Act on Promotion of Information and Communications Network Utilization and Information Protection, etc., and personal information collected and exposed is
  Subject to the Personal Information Protection Act. Detailed notices are in [README](README.md#features).

Legal responsibility for how code and documents submitted as contributions are used lies with the user who executes them.
I bear it. This repository is provided “AS IS.”

---

## Localization Policy

The reason for the existence of this repository is the original [Autumn-27/ARTEX](https://github.com/Autumn-27/ARTEX).
**Only the output displayed to the user is changed to Korean while preserving the judgment performance**.
Translation contributions that fall outside of this policy will not be accepted as they may degrade performance.

- **Do not translate the agent's internal reasoning prompts (body of action instructions).** In original (Chinese)
  Benchmarked behavior must be maintained. This text is about `agent/promptcatalog.go` and DB seed
  It is located at (`agent_prompts`). Translation causes drift in the agent's judgment.
- **Only the output exposed to users is forced to be in Korean.** Detection result (`report_finding`),
  These include the summary of facts (`record_fact`), final report, and conversation responses. This force
  `agent/prompt.go`'s code called `langDirective()` has a fixed tail for each role in the system.
  Appended at the end of the prompt. Modify this function to change the output language.
- **The original text of the command, payload, code, URL, and log is not translated.** This is because it is the original text required for analysis.
  Leave it as is.
- **The original Chinese language is preserved.** The document is `README.zh.md`, the UI string is `web/messages/zh.json`
  This makes it easier to compare changes to upstream repositories by leaving the original text as is. korean
  Translation is filled in `web/messages/ko.json`.
- When translating a new UI string, add it as a key in the message file rather than hardcoding it.
- **Forcing the output language is not a hard cap, but rather a prompt derivation.** `langDirective()` sets the output language to
  We only give **instructions** in Korean, but do not force fixation. Therefore, Korean fidelity is determined by model competency, role, and
  It depends on the context. Use competent models (frontier-grade) when validating localization changes.
  In low-cost/small models, the report/summary may revert to the original text (Chinese), so check whether the translation has been applied properly.
  Don't judge a cheaper model based solely on its output. `max_tokens` setting pitfalls when using OpenAI series models are:
  These are summarized in the “Model Selection and Output Language” section of the README (README.md#모델-선택과-출력-언어).
- **Procedures for keeping up with upstream changes are in the Maintainer Guide.** The original ARTEX
  When updated, the runbook reflects the preserved assets and translation targets and checks translation symmetry and drift.
  It is organized in [MAINTAINING.md](MAINTAINING.md).

---

## development environment

This project consists of **Go backend** (embedded frontend in a single binary) + **Next.js frontend**
It is configured.

The design intent of key features is outlined in the design documentation of the `docs/`. Vulnerability and Traffic Evidence
Functions that connect (autobinding of report agents, `traffic_refs` to `report_finding`, etc.)
When dealing with [Vulnerability Multi-Traffic Evidence Design Document](docs/finding-traffic-evidence-ko.md) first.
Please read. The original text (Chinese) is preserved in `finding-traffic-evidence-zh.md` in the same folder.

### required version

- Go 1.26 or higher (based on `go.mod`)
- Node.js 22 or higher (based on release workflow)
- Docker and Docker Compose (for local execution and verification)

### Backend (Go)

If you have Go installed locally, run the following from the repository root:

```bash
go build ./...
go vet ./agent/
go test ./agent/
```

If you don't have Go locally, you can verify the same with Docker. Module/build cache named volume
Putting it on makes re-execution faster.

```bash
docker run --rm -v "$PWD":/src -w /src \
  -v artexko-gomod:/go/pkg/mod -v artexko-gocache:/root/.cache/go-build \
  golang:1.26 sh -c 'go build ./... && go vet ./agent/ && go test ./agent/'
```

#### DB integration testing (requires postgres)

The above `go test ./agent/` must be attached to PostgreSQL or quietly run **DB integration tests.
Skip.** `agent`·`config`·`db`·`evidence`·`llmrec`·`server` six packages contain actual
There is a test that requires a database, but there is no environment variable `ARTEX_PG_DSN` and it cannot be set.
If there is no `database` entry in the file, the tests are moved to `--- SKIP` and the package is moved to `ok`.
It ends. So, after fixing these six packages and verifying without DSN, **local passes (ok), but PR's
The `go-db` operation may fail**.

To run these tests locally, launch PostgreSQL and pass `ARTEX_PG_DSN`. Below is
This is an example of running a CI-like `postgres:16-alpine` on an isolated network, named as above.
Reuse volume .

```bash
# 1) 격리 네트워크와 빈 postgres 를 띄웁니다 (CI 와 같은 이미지·계정).
docker network create artexko-db 2>/dev/null || true
docker run -d --name artexko-pg --network artexko-db \
  -e POSTGRES_USER=artex -e POSTGRES_PASSWORD=artex -e POSTGRES_DB=artex \
  postgres:16-alpine
until docker exec artexko-pg pg_isready -U artex -d artex >/dev/null 2>&1; do sleep 1; done

# 2) DSN 을 건네 DB 통합 패키지를 돌립니다 (DSN 의 host 는 컨테이너 이름입니다).
#    고친 패키지만 돌리려면 ./agent/ 자리를 config·db·evidence·llmrec·server 로 바꿉니다.
docker run --rm --network artexko-db -v "$PWD":/src -w /src \
  -v artexko-gomod:/go/pkg/mod -v artexko-gocache:/root/.cache/go-build \
  -e ARTEX_PG_DSN='postgres://artex:artex@artexko-pg:5432/artex?sslmode=disable' \
  golang:1.26 sh -c 'go test ./agent/ -count=1'

# 3) 정리합니다.
docker rm -f artexko-pg && docker network rm artexko-db
```

CI's `go-db` task forces these six packages **each into its own postgres** before merging.
Turn (`.github/workflows/ci.yml`). If you have fixed the DB integration package, please do the above before posting a PR.
We recommend that you check the package yourself.

### front end (web)

```bash
cd web
npm ci
npm run dev          # 개발 서버
npm run build        # 프로덕션 빌드
npm run build:static # 정적 내보내기 빌드(머지 게이트 · TypeScript 타입 검사 포함)
npm run check        # Biome 린트·포맷 검사(정보용 · 선재 부채로 아직 머지 게이트 아님)
npm run check:fix    # 자동 수정
```

Format and lint before commit are managed by Biome. `lint-staged` for staged files
Automatically rotates `biome check --write`.

### Full Run (Docker Compose)

```bash
cp .env.example .env     # POSTGRES_PASSWORD 설정
docker compose up -d     # artex + postgres 기동 → http://localhost:8787
```

---

## Contribution Process

1. First, **Open an issue.** For major changes, it is better to orient yourself to the issue before starting work.
   great. For small corrections (typos, links, obvious bugs), you can send a PR right away.
2. **Fork** the repository and create a topic branch. The branch names are `feat/...`, `fix/...`,
   Put the change character in front, like `docs/...` and `i18n/...`.
3. Write the change and **run the validation for that scope yourself.** If it is a Go change, then
   Pass `build`·`vet`·`test`. If the web changes, `npm run build:static`
   (Performs merge gate and TypeScript type checking together).
   `npm run check` (Biome) has not yet merged due to the remaining wire lint debt from upstream.
   Since it is not a gate and only runs for information purposes in `web.yml`, there is no need to pass the entire
   doesn't exist. Instead, I just need to check **that my change hasn't added any new errors** (when I commit
   `biome check --write` is automatically applied only to files staged by `lint-staged`).
   If you changed the document (`.md`), it should not be stored as `python3 -I scripts/check-doc-links.py`.
   Check that the link/image reference and document anchor (`#헤딩`) link are not broken. The anchor is
   Since slugs are created and compared in headings using the same rules as GitHub, changing the heading letters
   If you don't fix the anchor link pointing to that heading, it will happen here (CI's `docs`
   The workflow forces the same check into the merge gate). This check is performed on the repository root.
   [`.pre-commit-config.yaml`](.pre-commit-config.yaml) is also included with `docs` hook,
   If you set `pre-commit install`, it will run automatically when you commit (Python standard library only)
   It ends without Docker because it does not connect to the network).
4. **Open PR.** Title and description follow [PR template](.github/PULL_REQUEST_TEMPLATE.md),
   Write down what you changed and why you changed it and how you verified it. If you changed the UI, attach a screenshot.
5. If the change is visible to the user (function, localization, document, detection rule, etc.), go to [Change history (CHANGELOG.md)](CHANGELOG.md)
   Add one line to the `[Unreleased]` clause. You can skip any internal refactoring or test-only changes.

### commit message

Follows the conventions of existing commit history. The format is `type(scope): 설명`, and the description is written in Korean.

- `type`: `feat` · `fix` · `docs` · `chore` · `refactor` · `test` · `i18n` 등
- `scope`: Changed area (`agent` · `web` · `server`, etc.), can be omitted

This is an example.

```
feat(agent): 사용자 노출 출력을 한국어로 강제 (langDirective)
docs: 한국어 README 작성, 원본은 README.zh.md 로 보존
i18n(web): 대시보드 네비게이션 라벨 한국어 번역
```

---

## Contribution to detection rules and detection tests

This repository contains rules to **defend/detect** autonomous AI attacks such as ARTEX in [`detections/`](detections/).
Leave it. Deployable [Sigma](https://sigmahq.io) rules ([`detections/sigma/`](detections/sigma/)), for networks
[Suricata](https://suricata.io) rule([`detections/suricata/`](detections/suricata/));
[MITRE ATT&CK](https://attack.mitre.org/) coverage layer ([`detections/attack/`](detections/attack/)), and
A test ([`detections/tests/`](detections/tests/)) that reproducibly proves that these rules actually fire.
It consists of Please adhere to the agreement below when sending or modifying a detection rule. There are eight test suites:
Because much of the contract is enforced mechanically, if you just change the rules and don't update the test layer, the test will fail.

- **Ground all indicators to observable facts.** Strings written by rules, User-Agent, and behavioral thresholds are stored in this repository.
  It must be verified as factual from the source and not made as an assumption. Include the underlying source file in the rule
  Please clarify (e.g. indicator `artex-enrich/1.0` is checked at `enrich/enrich.go`). Metric Match Test
  ([`detections/tests/indicators/`](detections/tests/indicators/)) Each indicator has both an upstream source and a rule.
  It still checks for existence, so if an upstream resynchronization changes the source string, the test will fail unless you fix the rules as well.
  List of machine-readable indicators ([`detections/indicators/artex_indicators.csv`](detections/indicators/artex_indicators.csv))
  If changed, the MISP event ([`detections/indicators/artex_indicators.misp.json`](detections/indicators/artex_indicators.misp.json)) containing the indicator as is.
  We renew together. The MISP export test ([`detections/tests/misp/`](detections/tests/misp/)) produces two files:
  Forces a match as a unit and that the event is a valid MISP document loaded with pymisp .
- **Write down the limits honestly.** For Sigma rules, write in `description`, and for Suricata rules, write in the comments.
  It reduces the number of cases and the possibility of false positives. If it is a general hunting lead (e.g. Destruction Order) rather than an ARTEX-specific signature, then
  By specifying this, we avoid assuming that the attacker is ARTEX based on just one hit.
- **Pass static verification.** Sigma rules must pass SigmaHQ validator criteria with issue 0
  (`sigma check --validation-config detections/tests/sigma_lint/validators.yml`). The default `sigma check` is
  Since only the pySigma core verifier is run, SigmaHQ conventions such as title notation, field/log source classification, and reference links are limited to this standard.
  It gets filtered out. The four exceptions are SigmaHQ monorepo conventions that do not fit the standalone rule set, and the reasons for doing so are:
  I wrote it down at [`detections/tests/sigma_lint/validators.yml`](detections/tests/sigma_lint/validators.yml).
  Suricata rules should be loaded cleanly as `suricata -T`.
- **Put together a reproducible test** to see if the rule fires (or if the structure is valid).
  [`detections/tests/`](detections/tests/) Proved by the test below. For input, do not put the binary into the repository.
  It is generated deterministically every time, attributes that are unrelated to the engine version (existence of utterance, no false positives) are accurately asserted, and depending on the version,
  Assert the fluctuating value as the lower limit and record the reference value separately. Adding or modifying Sigma correlation rules to the backend
  The portability test ([`detections/tests/sigma_backends/`](detections/tests/sigma_backends/)) has several rules.
  Since we check whether the conversion is done in the backend, the backend support description of [`detections/README.md`](detections/README.md) and
  Please keep it straight.
- **Update the ATT&CK layer together.** If you add or change the `attack.*` tag to the rule,
  Technique and score of [`detections/attack/artex_navigator_layer.json`](detections/attack/artex_navigator_layer.json)
  Update accordingly. Since the match test enforces rule↔layer matching in both directions, it can be applied to rule tags or rules that are not in the layer.
  Any layer technique without it will fail.
- **Do not include content that reads as attack information.** Detection data in this repository only maintains defense/detection positioning.
  We do not accept descriptions that assist attacks, such as how to perform exploits or techniques to bypass detection.

The eight test suites can be run as is using Docker and do not commit the work to the repository. Each script is
If any assertion fails, you'll end up with a non-zero code, so you can put it right into your CI or pre-commit hook.

```bash
detections/tests/sigma/run.sh           # Sigma: sigma check + 백엔드 변환 + 지표 보존
detections/tests/sigma_match/run.sh     # Sigma: 원자 규칙이 악성 샘플에 발화·정상 샘플에 침묵
detections/tests/sigma_lint/run.sh      # Sigma: SigmaHQ 관례 전체 검증기 + 문서화된 기준
detections/tests/sigma_backends/run.sh  # Sigma 이식성: 상관 규칙이 여러 백엔드에서 변환되는지
detections/tests/suricata/run.sh        # Suricata: pcap 합성 → suricata -r → 경보 수 단언
detections/tests/attack/run.sh          # ATT&CK: 레이어 ↔ 규칙 양방향 정합
detections/tests/indicators/run.sh      # 지표: 규칙의 고정 지표 ↔ 상류 소스 양방향 일치
detections/tests/misp/run.sh            # MISP: 지표 CSV ↔ MISP 이벤트 동기화 + pymisp 유효성
```

To spin eight at once, use [`detections/tests/run-all.sh`](detections/tests/run-all.sh). CI-like
Execute the eight sequentially, and even if the previous suite fails, run the remaining suites to the end and report the PASS/FAIL summary for each suite.
It outputs, and if any one fails, it ends with a code other than 0. Here is an example of setting up this runner directly with a pre-commit hook:
Located at [`.pre-commit-config.yaml`](.pre-commit-config.yaml) in the repository root. `pip install pre-commit &&
When installed with pre-commit install`, only in commits where the detection rule or the upstream source fixed by the rule changes (such as CI),
Scope) Runner runs to catch rule/test inconsistencies before pushing them. The same configuration file contains links, images, and anchors within the document.
Also included is the `docs` hook to be tested (`check-doc-links.py` from contribution procedure #3 above).

These eight tests show that the repository CI ([`.github/workflows/detections.yml`](.github/workflows/detections.yml)) is
`detections/` Rotate for each push/PR that changes below. An indicator matching test is performed on the upstream source file pointed to by the indicator.
(`enrich/`·`selfupdate/`·`guard/`·`db/`·`cmd/artex/main.go`) changes, upstream resynchronization occurs between User-Agent and
Change the marker/default port to catch cases where rules become quietly obsolete. Therefore, changes that only change the rules and do not update the test layer, follow SigmaHQ conventions.
Broken rules or rules that are inconsistent with the source code are displayed in red in CI before merging.

The rule index and the basis and limitations of each rule are in [`detections/README.md`](detections/README.md), and the test assertion items and
The execution method is summarized in [`detections/tests/README.md`](detections/tests/README.md).

---

## license

This project is released under the **GNU Affero General Public License v3.0(AGPL-3.0)**.
By submitting a contribution, you agree that your contribution will be released under AGPL-3.0.
In particular, if you modify this project and make it available to users over a network (e.g. as an online service),
You must release the corresponding complete source code to its users. Full Terms: [LICENSE](LICENSE)
It's in the file.
