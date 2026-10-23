---
name: api-recon
description: This skill is called when collecting website API interfaces.
---

# API Recon (front-end interface reconnaissance)

Under the premise of **authorization**, discover as completely as possible: **back-end API** (path, method, parameter, response body), **front-end routing**, **UI function trigger point** (Tab, pop-up window, table operation, etc.).

---

## Boundaries and Prohibitions (A must-read for Agent · Violation means crossing the boundary)

This skill **only performs API/parameter reconnaissance**, not the vulnerability mining or penetration phase.

### task boundaries

| Scope | Allowed | Disallowed |
|---|---|---|
| **Target** | Enumerate path, method, parameters, routing, UI trigger points | SQLi/XSS/violation/explosion/fuzz vulnerabilities, package modification attacks, destructive operations |
| **Authentication** | Hook + stub/mock bypasses the **client** login door | Ask the user or guess the account password; try to submit the real login form |
| **Runtime** | Hook interface without credentials, use mock response to let SPA enter the post-login shell | Process that relies on real backend session to continue |

### Credentialless dynamic analysis (Phase 3 default)

1. Through `preload.js` / `runtime_harvest.js` **interception and stub** login, permissions, menu and other bootstrap interfaces;
2. The business query interface returns a mock body with correct structure, successful business code, and empty data**;
3. Enable the front end to still render the post-login page without a backend or in a 401 environment, thus triggering more XHR/fetch/WebSockets;
4. **Empty data, blank tables, placeholder UI are expected** – don’t turn to real login or vulnerability testing for this.

**One sentence**: Use mocks to support front-end routing and component mounting, and **only record outbound requests**; it doesn't matter what the backend returns, what matters is what interfaces the front-end **will send**.

### Process hard ban

| Prohibited | Alternatives |
|---|---|
| Before Phase 1 is completed, grep/curl/Read main entry `index-*.js` to extract API path | Run `OUTDIR/harvest_static.py` |
| Handwritten `extract_apis.py` and other scripts to replace harvest | Rerun after changing `OUTDIR/harvest_static.py` |
| The same grep/command failed ≥2 times but still repeated | Change strategy: read tool_logs, change harvest, check reference |
| Skip access control A/B and run `scripts/` original version directly | Copy to OUTDIR and change according to the target |
| Real username/password, OTP, OAuth and other authentication | stub/mock (see above) |
| Skip the stub on the grounds of "getting real data" and do override/injection testing | Only record outbound, which belongs to the recon boundary |
| Irreversible operations such as deleting, exporting sensitive data, and batch writing | The same applies to coverage clicks |
| Unfinished runtime + dynamic enumeration, claiming to have obtained all pages and interfaces | See "Complete Definition" or mark limitations |
| Unfinished parameter trigger matrix + diff, claiming to have mastered all parameters | Phase 3b matrix + Phase 5 diff |
| Required/optional inference from a single runtime sample | Multi-sample diff or validation rules/error inversion |

---

## Two-layer model + running mode

| Layer | Output | Upper Limit |
|---|---|---|
| **static** (JS bundle) | Full endpoint path, route draft, package point field candidate | No HTTP method; parameters must be Phase 1b; runtime splicing URL is missing |
| **Runtime** (live session) | Method + body + response + dynamic URL + WS/SSE; multi-sample diff completion parameters | The page must be actually rendered before the request is made; a single sample is not enough to determine required/optional |

| Operating Mode | Engine | Applicable |
|---|---|---|
| **depth** | `runtime_harvest.js` (Puppeteer) | API list, METHOD/params/response body, WS/SSE, reproducible batch running |
| **coverage** | browser + `preload.js` | Click Tab/pop-up window/table to get deeper coverage of function points |
| **both** | Depth first and then coverage | The most complete and the longest time |

**Parameter methodology** (no universal script): use harvest/regular for path; use **anchor window expansion + UI binding chain + multi-sample diff + error inversion** for parameters (for the grep recipe, see Section J of [reference.md](reference.md)).

---

## complete definition

Only when all are satisfied can recon be declared complete:

- [ ] **static**: Phase 1 harvest output `api_static.txt`, `routes.txt`, `js/`
- [ ] **Runtime**: at least one of depth or coverage; coverage/both must be **Hook effective + dynamic enumeration ring**
- [ ] **Enter shell**: When accessing the business path, it is not `/login` (note the hash routing)
- [ ] **Parameters**: coverage/both completion parameter trigger matrix + `param_samples.json`; Phase 5 merge `params_merged.json`
- [ ] **Depth** (if the module page is blank): Phase 4 permission tree is restored and re-run until the **module-level API** appears (not just locale/bootstrap)
- [ ] **Delivery**: Phase 5 output complete (see Phase 5 output table); `insert_assets` written service and endpoint assets

---

## Scripts and Access Control

`scripts/` is only a reference template. It is **not allowed** to run the original version directly and use it as the final result.

**Rules**: Read first → change according to the target → write `OUTDIR` (such as `recon/`) → record `CHANGES.md`; if not matched, rewrite according to the methodology and only borrow the structure.

| Access Control | When | Reference Script → OUTDIR Copy | Common Required Changes |
|---|---|---|---|
| **A (static)** | After Phase 0, before running harvest/spider for the first time | `harvest_static.py` / `spider_mpa.py` | **Most sites default to regex and can be run directly**; only change the endpoint regularity, webpack/Vite `publicPath`, MPA exclude/cookie when the manifest/dialect does not match |
| **B (runtime)** | After Phase 2, before running depth/coverage | `runtime_harvest.js` / `preload.js` + `config.json` | Cookie/localStorage key, neutralize success value, stubs, login regular, api prefix, hash/history |

**SPA forced order** (not interchangeable; Phase number takes precedence over "explore first then script"):

| Steps | Required | Prohibited |
|---|---|---|
| After Phase 0 is completed | Next entry Bash = `python3 OUTDIR/harvest_static.py <URL> OUTDIR` | curl/grep/Read main entry `index-*.js` (usually >500KB) |
| Access Control A | Copy the script → Make minor changes as needed → **Run immediately** | Manually extract the API first and then decide whether to harvest |
| Before Phase 1 is completed | `wc -l` verification output; 404 change harvest and try again | Handwritten extract script; grep repeatedly for undownloaded URLs |
| Phase 1b onwards | grep `OUTDIR/js/*.js` only | use main bundle instead of harvest |

- ✅ Copy `harvest_static.py` → (optional) change regex → **Run now**
- ❌ curl the main bundle → grep multiple times → write temporary extract → harvest at the end
- **MPA**: Next item after Phase 0 Bash = `python3 OUTDIR/spider_mpa.py ...`

---

## Tools and output constraints

| Constraints | Description |
|---|---|
| Large files | `index-*.js` >100KB **Disabled** Read/grep into context; batch with OUTDIR script |
| grep output | Must be `\| head -20` or `-m 5`; only the path summary is retained in the dialogue, do not paste the bundle fragment |
| Verification | Use `wc -l`, `ls \| wc -l`; do not Read the entire directory |
| Preliminary exploration of regex | Optional, ≤1 times, only ≤50KB small chunk or HTML; formal static is subject to harvest |
| reference | For recipes/templates/troubleshooting, see [reference.md](reference.md), do not repeat inline full text |

---

## Execution roadmap

```
Phase 0 分类 + OUTDIR
  → 门禁 A → Phase 1 harvest（★ 立刻运行 ★）
  → Phase 1b 参数逆向
  → Phase 2 鉴权三道门 → config.json
  → 门禁 B → Phase 3 运行时 + 参数矩阵
  → Phase 4 权限树（必要时）→ 重跑 Phase 3
  → Phase 5 合并报告 + insert_assets批量插入所有发现的服务、端点api资产，无论如何插入时不允许漏掉已发现的资产
```

Check in order; **Do not enter the next phase until the previous item is completed**.

1. [ ] **Phase 0**: First exploration of SPA/MPA; create `OUTDIR` → [Phase 0](#phase-0--classification)
2. [ ] **Access Control A + Phase 1**: Copy script → **immediately** harvest → `wc -l` verification → [Phase 1](#phase-1--static)
3. [ ] **Phase 1b**: Anchor point window expansion + binding layer → `param_candidates.json` → [Phase 1b](#phase-1b--parametric-inversion)
4. [ ] **Phase 2**: Three doors for authentication → `config.json` → [Phase 2](#phase-2--three-doors-of-authentication)
5. [ ] **Access Control B**: Adjust runtime script → [Phase 3](#phase-3--runtime)
6. [ ] **Phase 3**: depth / coverage / both; confirm entry into the shell; parameter trigger matrix → `param_samples.json`
7. [ ] **Phase 4** (if necessary): permission tree → patch stubs → rerun Phase 3 → [Phase 4](#phase-4--permission-tree-restoration)
8. [ ] **Phase 5**: Combine output + report + `insert_assets` → [Phase 5](#phase-5--consolidation-and-reporting)

---

## Phase 0 — Classification

Pull the entry HTML and **create `OUTDIR`** (do not change `scripts/` in the skill):

- **SPA**: empty shell + `<div id=app>` + chunk → Phase 1–5
- **MPA**: SSR + `<form>`, no endpoint bundle → after access control A:

```bash
python3 recon/spider_mpa.py <BASE_URL> <OUTDIR> [--cookie "session=..."] [--max 300] [--depth 5] [--exclude "logout|delete|destroy"]
```

Output `forms.txt`, `links.txt`, `api_inline.txt`. SPA if forms ≈ 0 → switch to Phase 1.

---

## Phase 1 — Static

Comply with [Scripts and Access Control](#scripts-and-access-control) · [Tools and Output Constraints](#tools-and-output-constraints).

```bash
python3 recon/harvest_static.py <BASE_URL> <OUTDIR>
```

Harvest: parse HTML script → webpack/Vite manifest → download all lazy chunk → output `js/`, `api_static.txt`, `routes.txt`, `chunkmap.txt`.

```bash
wc -l OUTDIR/api_static.txt OUTDIR/routes.txt
ls OUTDIR/js | wc -l
```

- Number of chunks vs manifest: 404 needs to be changed to harvest and try again. Do not manually curl chunks one by one.
- `api_static.txt` Too few → Relax the regular endpoint in OUTDIR and then rerun (see reference)

### Phase 1b — Parametric inversion

path is from Phase 1; parameter fields must be reconnoited separately. For grep rules, see [Tools and Output Constraints](#tools-and-output-constraints).

**Completion Standard**: Important interfaces can be answered - field name, transmission location, type inference, whether it is required, sample value, confidence level.

#### 1b.0 — Transmission Form

| Form | Where are the parameters | Static first |
|---|---|---|
| REST JSON | body + query | path next to anchor `(params\|data\|body)\s*:\s*\{` |
| GraphQL | `variables` | gql template, `$page: Int` |
| traditional form | urlencoded | `<form>`, `FormData` |
| File upload | multipart | `FormData.append` |
| Path parameters | `/user/:id` | Routing table + `useParams` / `$route.params` |
| Encryption/Signature | Package into `sign`/`data` | Hook encryption function input parameters (reference section D) |

Output: Each interface is marked `transport: query|json|form|graphql|encrypted`.

#### 1b.1 — Anchor window expansion

Using the known path as the anchor, expand the window to find the package object:

```bash
grep -n '"/api/user/list"' OUTDIR/js/*.js | head -20
grep -rhoaE '.{0,120}("/api[^"]+").{0,200}' OUTDIR/js/*.js | head -20
grep -rhoaE '(params|data|body|payload)\s*:\s*\{' OUTDIR/js/*.js | head -20
```

| Packaging layer | Parameter clues |
|---|---|
| axios instance | `data` / `params` |
| Unified request | Interceptor injection into global fields |
| OpenAPI Client | Generate method signature |
| React Query / SWR | hook second parameter |
| Composable view | composable 入参 |

Type residue: `yup`/`zod`/rules, `Form.Item name=`, embedded Swagger.

→ `param_candidates.json`：`{ path, fields[], source: "static-callsite", confidence }`

#### 1b.2 — Binding layer

```
Form field → onFinish/handleSubmit → transform → API payload
```

| Binding source | Technique |
|---|---|
| form submit | followed by submit → transform → API |
| Table search | `getFieldsValue()` → `params` |
| Routing | `:id` / `?tab=` |
| Interceptor | Global `tenantId`, paging, sign |
| enumeration select | `options` → API enumeration value |

DevTools call stack chases the package function from `fetch`/`XHR.send` up.

#### 1b.3 — Three questions for package assembly (≠ Three authentication gates for Phase 2)

| Question | What to answer |
|---|---|
| **Assembly** | Where is the payload build and transform traces |
| **Check** | required, pattern, enum |
| **transport** | path/query/body/multipart/header |

The interceptor gate (Phase 2) incidentally reads the global injection fields (Authorization, `X-Tenant-Id`, sign).

#### 1b.4 — Transition to Phase 3

Candidate fields come from static/binding layers; **required/optional/conditional dependencies** require Phase 3 parameter matrix + diff + Phase 5 error inversion.

---

## Phase 2 — Three doors of authentication

In `OUTDIR/js/` grep (with `head`), write `config.json` (see reference for recipe):

| Door | Question | Keywords |
|---|---|---|
| **Rendering Door** | How to tell if you are logged in? | `isLogin`, `getToken`, Cookie/localStorage |
| **Interceptor Gate** | What triggers jump `/login`? | `response_code`, `errno`, axios interceptor |
| **Content Gate** | Where do menus/permissions come from? | `menu`, `permission`, `role`, `acl`, `routes` |

Do not use localStorage keys as credentials - must be confirmed from the chunk/request chain.

**Exit = Access Control B**: Conclusion fell to `config.json`, and changed to `OUTDIR/runtime_harvest.js` / `preload.js`.

### Phase 2b — API Observation (optional)

Use `preload.js` in OUTDIR to confirm the session key, Authorization, and nested API URL:

| Configuration | Output |
|---|---|
| `recordDetail: true` | `__API_RECON_DETAIL__` |
| `observe.xhrHeaders: true` | headers observation |
| `extractUrlsFromResponse: true` | Response inner child API |
| `observe.storageReads/cookieReads: true` | backfill config |
| `neutralizeVueRouter: true` | `__API_RECON_ROUTES__` |

Coverage is exported in each round: `__API_RECON_LOG__`, `__API_RECON_DETAIL__`, `__API_RECON_ROUTES__`, `__API_RECON_OBSERVE__`.

---

## Phase 3 — Runtime

Must have passed gate B; comply with [Borders and Prohibitions](#boundaries-and-prohibitions-a-must-read-for-agent--violation-means-crossing-the-boundary) · No credentials mock policy.

`config.json` Sets `"runtimeMode": "depth" | "coverage" | "both"` (see reference for template).

### Hook and stub (shared by depth + coverage)

| Layer | Scope | Purpose |
|---|---|---|
| L1 accurate | auth/authority/bootstrap stub | Pass first screen authentication |
| L2 negative correction | All JSON responses | Unregistered code → Success |
| L3 pocket | `/api` that missed L1, etc. | Empty success body, open UI |

- **depth**: fake auth + `forward` change business code + `stubs`; traverse `routes` (hash/history); output `runtime_api.json`
- **coverage**: **document-start** injects `preload.js` (CDP `addScriptToEvaluateOnNewDocument` or Userscript)

Verification: `window.__API_RECON_PRELOAD__` exists; the service path does not return `/login`.

```bash
cd recon && npm install
node runtime_harvest.js config.json
```

### 3b — coverage dynamic enumeration (required)

1. Main navigation/sidebar — each click, wait 1–3s for network
2. Tab — `role=tab`、`.ant-tabs-tab`
3. Table - first row view/edit/details
4. Toolbar - Export, Filter, New (**Avoid irreversible deletion**)
5. Each module - merge API/routing
6. SPA - Uncovered path controlled `pushState` for `routes.txt` (MPA disabled)

**Parameter trigger matrix** (required): Each module is recorded once according to the operation type, **diff multi-sample**:

| Operation | Usually extra parameters |
|---|---|
| First screen of list | Pagination + default filter |
| Click search | keyword, filter |
| Advanced filtering | More optional |
| New/Edit | Complete entity |
| Batch/Export/Sort | `ids[]`, `exportType`, `sortField` |

**outbound body/headers are still true under stub** - subject to request. Record → `scan_raw.json`, `param_samples.json`, `api_detail.json`.

- **Vue**：`neutralizeVueRouter: true` + document-start preload
- **React**: `routes.txt` + sidebar click + `pushState`
- **both**: 3a depth first, then 3b coverage

---

## Phase 4 — Permission tree restoration

**Trigger**: The module page is blank / only bootstrap per route (such as locale) → the content gate has not passed.

| Phenomenon | Meaning |
|---|---|
| Entering the shell successfully | Rendering door + interceptor door passed |
| Sidebar missing items/clicks are blank | stub shape or incomplete permission code |
| Each route API is the same and very few | `v-if permission` failed |
| `routes.txt` is much smaller than bundle | Must be completed from auth module |

```bash
grep -rhoaE '"/api[^"]*(permission|perm|role|menu|acl)[^"]*"' OUTDIR/js/*.js | sort -u | head -30
grep -rhoaE 'userRouteAuth|getResultTree|routeMap|routeLink|menuList|authList' OUTDIR/js/*.js | head -20
```

Typical chain: `role_permissions` (flat codes) + `permissions/all` (tree) → `getResultTree` → `userRouteAuth[CODE].url`.

```bash
python3 recon/extract_route_map.py recon/js recon/
python3 recon/build_perm_tree.py recon/js recon/ --config recon/config.json
```

Intermediate output: `route_map.json`, `userRouteAuth.json`, `permissions_tree.json`, `*_stub.json`, `perm_codes_all.txt`.

Stub check: outer `response_code` is consistent with the interceptor door; flat codes are aligned with tree; `routes` covers `route_map` all links.

**Rerun Phase 3** after updating `config.json`. Large SPA adjustable `waitUntil`, `routeTimeout`, `perRouteMs` (see section reference A3/I).

---

## Phase 5 — Consolidation and Reporting

### output table

| Documentation | Stage | Content |
|---|---|---|
| `js/`, `api_static.txt`, `routes.txt`, `chunkmap.txt` | 1 | static bundle and path |
| `param_candidates.json` | 1b | Static parameter field candidate |
| `config.json` | 2 | Three doors + runtime configuration |
| `runtime_api.json` | 3a | depth detailed recording (including WS/SSE) |
| `param_samples.json`, `scan_raw.json`, `api_detail.json` | 3b | Multiple samples, click logs, detail |
| `route_map.json`, etc. | 4 | Permission tree intermediate file (if executed) |
| `params_merged.json` | 5 | Merge parameter fields + confidence |
| `api_merged.txt` | 5 | `METHOD /path [params] [static\|runtime\|both]` |
| `site_map.json` | 5 | Routing, API, params, function points, limitations |
| **insert_assets** | 5 | Write all service and endpoint assets into the asset library |

### 5b — Parameter merging

From `param_samples.json` diff, **No generic merge script**. See reference J7 for confidence rules (high/medium/low/pending).

### 5c — Error backcasting

Incomplete requests can be sent within the authorization scope to read 400 (** parameter recon, non-vulnerability test**): `field 'x' is required`, enumeration error, etc. Note `data` packaging, `variables`, and `bizData` before encryption.

Reports must note: runtimeMode, static/runtime API count, parameter confidence, uncovered modules, `CHANGES.md` summary relative to the reference script.

`site_map.json` suggested structure:

```json
{
  "site": "https://example.com",
  "runtimeMode": "both",
  "appType": "vue-spa",
  "routeGuardStrategy": ["nav-neutralize", "L1-auth", "L2-patch", "forward"],
  "apisFromStatic": [],
  "apisFromRuntime": [],
  "apis": [],
  "params": [{ "method": "POST", "path": "/api/user/list", "transport": "json", "fields": [] }],
  "frontendRoutes": [],
  "routesVerifiedByClick": [],
  "featuresTriggered": [],
  "limitations": ""
}
```

See [reference.md](reference.md) for more fields and grep recipes.

---

## General instructions

- **Framework independent**: webpack/Vite/Angular lazy load method is the same
- **Transport**: REST/JSON, GraphQL, WebSocket, SSE; gRPC-web is not in scope
- **SSR**: Client fetch can be recorded; RSC/Server Actions are not fully enumerable
- **Blind spot**: JSVMP, WASM, HMAC/mTLS strong verification → static + annotation limitations
- **Parameter blind area**: Conditional linkage, hidden params, WASM package → "To be triggered"/"Unreachable"
- **Static is a safety net**: Static can still enumerate endpoints when the runtime is blocked

---

## additional resources

- Grep recipe, `config.json` template, troubleshooting, Hook, parameter reverse section J, site_map template: **[reference.md](reference.md)**
- For the reference script path, see the [Scripts and Access Control](#scripts-and-access-control) table
