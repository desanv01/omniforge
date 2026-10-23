# Upstream synchronization and prevention of translation drift (maintainer guidance)

Korean · [English](MAINTAINING.en.md)

This document was published by **maintainer** in the original repository [Autumn-27/ARTEX](https://github.com/Autumn-27/ARTEX).
This outlines the process for maintaining Korean localization while keeping up with changes. Scope of contribution·Legal responsibility·
Localization policy is in [CONTRIBUTING.md](CONTRIBUTING.md), user guide is in [README.md](README.md).
Therefore, this document focuses only on **how to actually enforce** that policy.

The core goal of localization can be summarized in one sentence: to the user while preserving the **judgment performance of the original.
Only the visible output is converted to Korean**. Since this boundary is likely to be disturbed each time the upstream stream is updated,
Prevent translation drift with the procedures and checks below.

---

## 1. Localization structure at a glance

This repository **forks** the upstream ARTEX and builds Korean localization commits on top of that history.
All commits from upstream `main` are included in the history of this repository, with localization commits added on top of them.
there is. Therefore, bringing about an upstream change involves "checking the differences with the upstream `main` and preserving them."
It becomes a matter of “selecting and reflecting what to translate.”

The output is divided into three branches:

- **Property to retain the original text** (Section 2 below). Translation breaks performance or upstream contrast.
- **Force a fixed output language in your code**. `langDirective()` of `agent/prompt.go` is the system for each role.
  At the end of the prompt, add the instruction "Write user exposure output in Korean."
- **User-exposed strings translated into Korean**. The UI is in `web/messages/ko.json`, on the server
  User response phrases are placed in naming constants in each Go file.

---

## 2. Assets that preserve the original text (translation prohibited)

The following assets are not translated and remain in their original text (Chinese or English): When an upstream change touches this asset
**Reflected without translation**.

- **Agent internal inference prompt (brain body).** `agent/promptcatalog.go` and DB seed.
  This is the text of the action instructions in `agent_prompts`. The behavior benchmarked in the original (Chinese) must be maintained.
  Therefore, when translating, there will be a drift in judgment.
- **A string that doubles as a display and agent input.** A string that is visible on the activity timeline and at the same time as a planner/reporter.
  Some phrases are fed back to the input context (abort reason, intercept blocking message, traffic evidence helper)
  etc.) preserves the original text because one record serves two purposes. The basis for decision is
  It is written on a case-by-case basis in `work/DECISIONS-FOR-JIWOO.md`'s "Brain Alert Records".
- **Original Chinese document/string.** Document is in `README.zh.md`, UI string is in `web/messages/zh.json`.
  Leave the original text as is to make it easier to compare changes upstream. Korean translation is `web/messages/ko.json`
  Fill only.
- **Original text of command, payload, code, URL, identifier, log.** It is not translated as it is the original text required for analysis.
  Go code comments also have the lowest priority, leaving the original text until the end of the upstream collation.

---

## 3. Upstream tracking base

The upstream remote must be set as follows. If not, add it.

```bash
git remote add upstream https://github.com/Autumn-27/ARTEX
git remote -v   # upstream 이 보이는지 확인
```

The upstream base commits for which localization has now been reflected are as follows:

- **Base = `d003372`** (upstream `main`, merged on 2026-10-03, PR #189 `fix/sse-same-origin`).

This value means "All changes upstream of this commit are stored in this repository." Upstream change
Each time you reflect, update this base using the method in Section 7.

---

## 4. Procedure for bringing about upstream changes

### 4.1 Download upstream and check the differences

```bash
git fetch upstream
git rev-list --count d003372..upstream/main        # 미반영 상류 커밋 수
git log --oneline d003372..upstream/main           # 미반영 커밋 목록
```

`git fetch` only updates the upstream remote tracking branch, so it does not affect the work tree and `HEAD`.
It doesn't. If the unreflected commits are 0, you are in sync with upstream and there is nothing more to do.

### 4.2 Classify changed files

We look at which files were touched by unreflected commits and divide them into preserved assets and translation targets in Section 2.

```bash
git log --name-status --oneline d003372..upstream/main
```

The classification criteria are as follows:

- If the `agent/promptcatalog.go`·`agent_prompts` seed and the display/input string in Section 2 have changed
  → **Reflected without translation**.
- If the Go backend logic (`db/`·`llmrec/`·`server/`, etc.) has changed → The logic should be reflected as is.
  **Check for new user response phrases** (`writeErr`, etc.) and translate them into Korean constants.
- If the UI (`web/src/**`) has changed and a **new screen string** has been created → Do not hardcode it.
  Add with the same key to `web/messages/zh.json` (original text) and `web/messages/ko.json` (translation).
- **Upstream indicators fixed by detection rules** (Prober User-Agent of `enrich/enrich.go`, Prober User-Agent of `selfupdate/`
  Self-updating User-Agent, audit marker of `guard/guard.go`, destroy command deny list of `db/db.go`,
  If the default listen/record proxy port of `cmd/artex/main.go` has changed → `detections/`
  Sigma·Suricata rules, ATT&CK layer, and `detections/indicators/artex_indicators.csv`
  Set the value to the new value. This indicator is not subject to translation, but **the basis for detection**, so if the upstream changes the value,
  Rules quietly get old. The indicator match test in 5.4 automatically catches this misalignment.

### 4.3 Reflect

After merging or selectively reflecting functions, the new strings identified in 4.2 are translated into Korean.
During the merging process, the keys of `ko.json`·`zh.json` are misaligned or the original text is leaked into the user exposed space.
Because it is easy, be sure to perform the test in Section 5 immediately after reflection.

> **Example (commit not reflected as of 2026-10-05).** The result of `git fetch upstream` is upstream of `main`.
> `b55ceb1` is ahead, with 2 commits compared to base `d003372` (`86729b6` model fallback approval token metering)
> Feature + merge commit `b55ceb1`) is not reflected. This commit is `db/llm_usage.go`·`llmrec/llmrec.go`·
> Go logic such as `server/intercept.go`·`server/server.go` and `web/src/app/(main)/system/intercept/page.tsx`·
> It touches `web/src/lib/api.ts`·`web/src/lib/mock/handler.ts`·`web/src/lib/types.ts`.
> Therefore, the maintainer reflects the Go logic as is and displays a new screen on the intercept settings page.
> Just extract and translate the string using the `ko.json`·`zh.json` keys. (These two commits are, at the time of this writing,
> Since it has not been reflected yet, the base is set to `d003372`.)

---

## 5. Translation symmetry and drift checking

After upstream reflection or translation work, check the three things below.

### 5.1 ko ↔ zh Message Symmetry and User Exposure CJK

The keys of `ko.json` and `zh.json` must be exactly the same, and there must be no Chinese characters left in the `ko.json` value.
do. The script below prints three numbers.

```bash
python3 - <<'PY'
import json, re
ko = json.load(open('web/messages/ko.json'))
zh = json.load(open('web/messages/zh.json'))
def flatten(d, p=''):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items(): out.update(flatten(v, p + '/' + k))
    elif isinstance(d, list):
        for i, v in enumerate(d): out.update(flatten(v, p + '/' + str(i)))
    else: out[p] = d
    return out
fk, fz = flatten(ko), flatten(zh)
han = re.compile(r'[㐀-鿿]')
print('ko leaf keys :', len(fk))
print('zh leaf keys :', len(fz))
print('key symdiff  :', len(set(fk) ^ set(fz)))        # 0 이어야 함
print('ko vals w/CJK:', sum(1 for v in fk.values() if isinstance(v, str) and han.search(v)))  # 0 이어야 함
PY
```

Baseline values ​​(2026-10-05): `ko leaf keys = 2950`, `zh leaf keys = 2950`, `key symdiff = 0`,
`ko vals w/CJK = 0`. The number of keys can be increased by upstream reflection, but ko and zh must always be the same.
`key symdiff` and `ko vals w/CJK` must always be 0.

### 5.2 Ensure original text preservation of brain assets

The brain body maintains the original Chinese text, so in the test below, **if the number of Chinese character lines falls to 0**, it will instead
This is a signal that the brain has been contaminated by translation mistakes.

```bash
python3 -c "import re; han=re.compile(r'[㐀-鿿]'); t=open('agent/promptcatalog.go').read(); print('promptcatalog.go CJK lines =', sum(1 for l in t.splitlines() if han.search(l)))"
```

Base value (2026-10-05): `promptcatalog.go CJK lines = 70`. If this number decreases significantly, it means that the brain text has been translated.
Confirm.

### 5.3 Verify that the original text is not leaked in the build output.

If Chinese language appears in the freerender HTML after statically exporting the UI, the translation is missing.

```bash
cd web && npm ci && NEXT_EXPORT=1 npm run build   # out/ 생성
# out/**/*.html 에서 가시 텍스트의 중국어 한자가 0 인지 확인
```

### 5.4 Detection indicators still match upstream sources

The rule of `detections/` is the string that the upstream actually sends (prober User-Agent, self-update)
Based on User-Agent·Audit Marker·Destruction Command Deny List). If an upstream resynchronization changes this value,
All translation checks pass, but only the distributed rules quietly stop matching. The test below shows that each indicator
It bi-directionally checks to see if both the upstream source and the rule are still there, so they run together after the resynchronization.

```bash
detections/tests/indicators/run.sh   # Docker 로 격리 실행, RESULT: PASS 이면 일치
```

If it fails, you can determine which indicator was off and in what direction (whether the upstream source changed or the rule changed).
Since it is output, adjust the rule layer to the new value according to the last classification standard in 4.2. This test repository
Rule tree also exists in CI ([`.github/workflows/detections.yml`](.github/workflows/detections.yml))
The above upstream source file is automatically rotated every time a change is made to the push/PR, and resynchronization drift is caught at the merge gate.

If you **pinned the new upstream source file** while adding a new indicator (e.g. port indicator for `cmd/artex/main.go`)
(as when inserting), be sure to add that file to the `push`·`pull_request` `paths` filters in the above workflow.
If omitted, PR that only changes the source will not ignite the indicator test, and drift will silently open the merge gate.
It passes. This synchronization itself is also automatically checked by the indicator test (the fifth check "CI triggers this
test when any pinned source changes"): All non-`detections/` sources that the test reads from both `paths`
If it is not listed in the block, the test will fail, so it will not be merged with source fixation and CI firing conditions misaligned.
It doesn't.

### 5.5 When raising the detection test tool pin

The detection test uses `sigma-cli`, SigmaHQ verifier plugin (`pySigma-validators-sigmahq`), and Suricata images.
Run a fixed version (default value for each `run.sh`, can be overridden with environment variables). Upstream if you post this pin
This may result in **drift** towards the tool and not towards the source. In particular, SigmaHQ verifier introduces new conventions with each update.
By adding checks, `detections/tests/sigma_lint/run.sh` may flag new issues.
At that time, you can adapt the rules to the new convention, or write down the reasons if the convention does not fit the standalone rule set.
Exclusion of [`detections/tests/sigma_lint/validators.yml`](detections/tests/sigma_lint/validators.yml)
Add to list. If the backend plugin changes support, the `sigma_backends` test will give the same signal.

---

## 6. Final verification through build and testing

After incorporating changes, follow [the development environment in CONTRIBUTING.md](CONTRIBUTING.md#development-environment) for the backend and
Verify the frontend. If you don't have Go locally, you can run the same with Docker.

```bash
docker run --rm -v "$PWD":/src -w /src \
  -v artexko-gomod:/go/pkg/mod -v artexko-gocache:/root/.cache/go-build \
  golang:1.26 sh -c 'go build ./... && go vet ./... && go test ./... -count=1'
```

When translating a user-disclosed phrase, a regression test (`*_localized_test.go`) that asserts the phrase is included.
Also, even if an upstream change brings Chinese back later, the test will catch it. Translation verification is a must
It is a capable (frontier level) model. In low-cost and small models, the output can be returned to the original text.
You should not judge whether a translation is applicable based on the output alone.

---

## 7. Base update record

Once the upstream changes have been reflected and verified, the **base commit value in Section 3 of this document is replaced with the new upstream commit.
Update** and include the change in the same commit or a commit that follows it. If you do this, the next maintainer will
You can check “how much has been reflected” in one place in this document.

Commit messages follow [commit message rules in CONTRIBUTING.md](CONTRIBUTING.md#commit-message).
For example, the upstream sync commit would be written as:

```
chore(upstream): 상류 d003372..b55ceb1 반영 (intercept 토큰 계량) + 신규 UI 문자열 번역
```

---

## 8. Review and verification rules (common pitfalls)

When checking upstream reflection, translation, and document enhancement, write down two pitfalls that maintainers fall into repeatedly.
Leave it. In both cases, “the inspection method itself is wrong, mistaking something that is healthy as broken,” so it is unnecessary.
It is fixed as a rule to prevent reversal.

### 8.1 Repository CI status can be checked by specifying the repository

This repository is a fork of upstream ARTEX, so there are `origin` (jiwoochris/artex-ko) and `origin` in the local `git remote`.
`upstream` (Autumn-27/ARTEX) is also registered (see Section 3). In this state, the `gh` command
If you do not specify a repository, `gh` will **pick the upstream repository as default**, which our workflow does not have.
Shows the results of upstream execution. Then, seeing that the upstream CI is green, **our CI passed.
I am mistaken**, or my workflow (`ci.yml`·`detections.yml`) is incorrectly marked as “HTTP 404 … not found”.
You can judge.

So, when checking CI, always specify the repository.

```bash
gh run list -R jiwoochris/artex-ko --workflow ci.yml --limit 5
gh run list -R jiwoochris/artex-ko --workflow detections.yml --limit 5
```

Once set, you can change it to view our repository as default by omitting `-R`. However, this
The settings are **local gh settings** and are not committed to the repository, so they will need to be redone on a new machine or new checkout.
Must be specified.

```bash
gh repo set-default jiwoochris/artex-ko
gh repo set-default --view   # jiwoochris/artex-ko 가 보이는지 확인
```

### 8.2 External links in the document are checked with GET like a browser.

Defense Guide ([`docs/defense-ko.md`](docs/defense-ko.md)·[`defense-en.md`](docs/defense-en.md))
Section 7 contains links to official domestic channels (boho.or.kr·fsec.or.kr·pipc.go.kr). this link is alive
When checking for presence, if you only check with `curl -I` (HEAD request) or the default User-Agent, **a normal link is broken.
It is mistaken for**. Domestic public and security agency sites refuse simple verification for the following three reasons:
Because.

- **Reject HEAD request.** For example, fsec.or.kr returns 400 for `curl -I`(HEAD).
- **Blocks the default `curl` User-Agent.** fsec.or.kr and pipc.go.kr are sent to the default UA.
  It also returns 400 for GET requests (200 if sent to browser UA).
- **Redirect to another address.** pipc.go.kr is from `www.pipc.go.kr` to `pipc.go.kr/np/`
  It redirects twice, so if you don't follow the redirects you miss the final state.

Therefore, the link confirmation is **browser User-Agent, GET, and follows the redirect**.

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
for u in https://www.boho.or.kr https://www.fsec.or.kr https://www.pipc.go.kr; do
  curl -sS -L -A "$UA" -o /dev/null -w "$u -> %{http_code} %{url_effective}\n" "$u"
done
```

If the final status code is 200, the link is valid. If the status code is 400 or 403, the link is broken.
Rather, first suspect that **the confirmation method is blocked by the server's access policy**, and use HEAD·Basic
Remove factors such as UA/redirect untracked one by one and check again. (As of confirmation on 2026-10-06
All three links are 200 in the above method, and pipc.go.kr is 200 after redirecting twice.)

`scripts/check-external-links.py` automatically automates this manual procedure. All `.md` tracked
Collect external links outside of codefence and inline code (excluding reservations and placeholder hosts), and
Likewise, check the status through browser UA, GET, and redirect tracking, and retry network errors, 5xx, and 429.
Distinguish between temporary flicker and real disturbance. Divide the result into four: OK(2xx·3xx) ·
RESTRICTED (401, 403, 405, 429, host is alive, only confirmation method is blocked) · ALLOWED
(Dead link of upstream inheritance that we cannot fix, written in `scripts/external-links-allowlist.txt`) ·
DOWN (404·410·5xx·Connection error, most likely broken).

- Preview only inspection target without network: `python3 -I scripts/check-external-links.py --list`
- Release/cycle check (abnormal termination if there is a new broken link): `python3 -I scripts/check-external-links.py --strict`

External link survival is flaky so we **don't put it in the merge gate**. Non-blocking workflow instead
[`external-links`](.github/workflows/external-links.yml) runs every Monday and manually.
Turn `--strict`, and if a new DOWN that is not in the allowlist is created, it will be displayed in red. Upstream text preservation
Dead links that a file inherits (e.g. a missing contributor account credited to `CHANGELOG.zh.md`) we
Since it cannot be fixed, write it in the allowlist with a reason and exclude it from strict checks.

---

## 9. Release Publishing Pipeline

If you slide the version tag (`v*`), [`.github/workflows/release.yml`](.github/workflows/release.yml) will appear.
Create a binary for the platform and a multi-architecture Docker image when the conditions are met. This fork is still
Since this workflow has never run because the release tag has never been broken, this section
We organize what is assumed, what is produced, and whether that premise fits the current storage structure.
Pushing a tag creates a GitHub Release in the public repository, so stopping a release occurs only after the decision to publish has been made.
do.

### How to break a 9.1 release

Sliding a tag starting with `v` will trigger the workflow.

```bash
git tag v0.3.15
git push origin v0.3.15
```

### 9.2 What pipelines do

The workflow is divided into five jobs:

- **frontend.** Export the frontend statically once (`web/out`) and export the output to `web-dist`
  Uploaded as an artifact. The binaries job below takes this output back and reuses it for each target.
- **binaries.** Intersects five targets (linux amd64·arm64, darwin amd64·arm64, windows amd64)
  Compile and zip per target. The linux amd64 binary has a `artex -h` smoke test.
  Run it to see if the binary actually runs.
- **release.** Collect all zips, create a `SHA256SUMS` checksum, create a GitHub Release, and
  Attach checksum.
- **docker-gate.** Check if the `DOCKERHUB_USERNAME`·`DOCKERHUB_TOKEN` secret is set.
  The result is passed on to the execution conditions of the next job.
- **docker.** Runs only when the above secret is present, and receives the Linux binary cross-compiled by binaries.
  Build a multi-architecture image and upload it to Docker Hub. If you don't have a secret, skip this job.
  A release CI ends with a binary release only, with no red failures.

### 9.3 Does the build premise match the repository structure?

The pipeline operates on the following three premises, and these premises all fit with the current storage structure:
I verified this by reproducing the binaries job locally.

- **Frontend embed.** `web-dist` (= contents of `web/out`) uploaded by the frontend job is transferred to the binaries job.
  Receive it as `server/webui/dist`, and `//go:embed all:webui/dist` of `server/webui_embed.go` takes its place.
  Embed it in your binary. So without rebuilding the frontend that caught the binaries
  Call [`build.sh`](build.sh) with `ARTEX_SKIP_FRONTEND=1`.
- **Binary/package path.** `build.sh --target <os>/<arch>` is `dist/artex-<os>-<arch>/artex`
  Create the binary and zip package below `dist/`. The zip contains a startup script (Linux·
  `start.sh` for macOS, `start.bat` for Windows), `skills/`, `config.example.json`, `README.md`
  I go in.
- **Copy the binary of the Docker image.** binaries Grab the linux binary to `bin-linux-<arch>`
  Upload it separately as an artifact, and the docker job receives it as `dist/<arch>/artex`.
  `COPY dist/${TARGETARCH}/artex` of [`Dockerfile`](Dockerfile) is buildx in multi-architecture build.
  Select the path as `TARGETARCH`, which is filled in for each platform.
  [`.dockerignore`](.dockerignore) does not exclude `dist/`, so the binary is in the build context.
  Included.

### 9.4 Still to be decided: Docker image namespace

The docker job currently names the image upstream as `autumn27/artex`, and places this fork in a certain location.
Whether to issue in a namespace is a separate decision (`work/DECISIONS-FOR-JIWOO.md` item 8). decision
There will be no Docker Hub secret until it is released, and in the meantime releases will only contain binary zips and checksums.
Issue (skips the docker job).

### 9.5 Local pre-verification without tags

To verify only the pipeline premise without breaking the public release, reproduce the binaries job locally.
If you don't have Go locally, you can run the same with Docker.

```bash
# 1) 프런트엔드 정적 내보내기(release.yml 의 frontend 잡에 해당)
cd web && npm ci && npm run build:static && cd ..
# 2) binaries 잡이 아티팩트를 받는 자리에 배치
rm -rf server/webui/dist && mkdir -p server/webui/dist && cp -a web/out/. server/webui/dist/
# 3) 한 대상만 binaries 잡과 같은 환경으로 빌드
docker run --rm -v "$PWD":/app -w /app \
  -e ARTEX_SKIP_FRONTEND=1 -e ARTEX_SKIP_NPM_CI=1 \
  -e ARTEX_COMPRESS=0 -e ARTEX_PACKAGE=1 -e ARTEX_PACKAGE_DIR=dist \
  -e ARTEX_BUILD_VERSION=v0.0.0-local \
  golang:1.26 bash -c 'apt-get update && apt-get install -y zip && ./build.sh --target linux/amd64'
# 4) 산출물 확인: dist/artex-linux-amd64/artex · dist/*.zip · dist/SHA256SUMS
```

`dist/artex-linux-amd64/artex` is a statically linked ELF, and if you give `-h`, it prints usage instructions and exits.
It ends with code 0. This is the behavior that the binaries job's smoke test confirms. build output
(`dist/`·`server/webui/dist/`) is not committed to the repository (excluded by `.gitignore`).
