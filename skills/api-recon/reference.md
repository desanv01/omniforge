# api-recon — Reference manual

Grep recipes, `config.json` templates and troubleshooting. All greps are performed against the `js/` directory. When bundling a single line, you can first use `js-beautify` or `sed 's/}/}\n/g'`, usually raw grep with a context window is sufficient.

## Script description

All files in `scripts/` are **reference templates** and must be adjusted according to the target site before execution. Typical changes:

| Script | Commonly needed adjustments |
|---|---|
| `harvest_static.py` | endpoint regular, webpack/Vite manifest parsing, micro-frontend publicPath, retry/concurrency |
| `runtime_harvest.js` | neutralize field name and success value, stub matching rules and body structure, routes source, WS recording, `waitUntil`/`routeTimeout`/`proxy` |
| `preload.js` | `loginPathRe`, L1 stubs, `neutralize.fields`, `apiPattern`, whether to enable L3, `recordDetail`, `observe.*`, `neutralizeVueRouter` |
| `spider_mpa.py` | `--exclude` destructive links, cookies, depth/max, same domain filtering |
| `extract_route_map.py` | `routeMap` / `routeLink` regular, KEY naming pattern |
| `build_perm_tree.py` | `userRouteAuth` parsing, `ROOTS`/`PREFIX_PARENT` level heuristic, stub outer field name |
| `config.json` | A unified entrance to the exclusive parameters of all the above sites |

It is recommended that the adjusted file be placed in the task working directory (such as `recon/`), and the specific changes relative to the reference script will be noted in the report.

---

## A. Three reverse gates

### A1. Rendering Gate — "How to determine if you are logged in?"

```bash
grep -rhoaE '.{0,40}(isLogin|isAuthenticated|loggedIn|hasLogin|requireAuth)\b.{0,80}' js | head
grep -rhoaE 'function (getUser|getToken|getAuth)[0-9]?\([^)]*\)\{.{0,200}' js | head
grep -rhoaE '(localStorage|sessionStorage)\.getItem\("[^"]+"\)' js | sort -u
grep -rhoaE '(Cookies?|cookie)\.(get|load)\("[^"]+"\)' js | sort -u
grep -rhoaE '\batob\(|JSON\.parse\(|jwt|decode' js | head
```

Find the link `isLogin = f(getUser())` → `getUser = decode(storage.read(KEY))`, and determine the **storage key**, **container** (Cookie vs localStorage), and **encoding**:

| Encoding | config forgery method |
|---|---|
| plain text string / `"1"` / token | `"value": "anything-truthy"` |
| `JSON.parse(x)` | `"value": "json:{\"id\":1,\"username\":\"admin\"}"` |
| `JSON.parse(atob(x))` | `"value": "b64json:{\"id\":1,\"username\":\"admin\"}"` |
| JWT | Unsigned/`alg:none` JWT, or in-bundle key signature |
| Encryption (SM2/AES/RSA) | Find hardcoded keys; render gate can be forged only if it only needs a decodable blob; otherwise, it is a static secret |

→ Write `cookies` / `localStorage`.

### A2. Interceptor Gate — "What triggers /login?"

```bash
grep -rhoaE '.{0,60}(interceptors\.response|axios|request\.use).{0,120}' js | head
grep -rhoaE '.{0,40}(response_code|errcode|errno|\bcode\b|\bret\b|\bstatus\b)\s*[=!]==?\s*[\-0-9]{1,4}.{0,60}' js | head -20
grep -rhoaE '.{0,40}(未登录|请重新登录|登录已过期|unauthorized|登录失效|授权|token.{0,10}invalid).{0,40}' js | head
grep -rhoaE '.{0,30}(location\.href|router\.(push|replace)|navigate)\([^)]*login[^)]*\)' js | head
```

Determine: **field name**, **success value** (usually `0` or `200`), **failure value that triggers the jump**. Verify with junk session:

```bash
curl -sk -X POST -H 'Cookie: <fakekey>=junk' https://target/api/<protected> -d '{}' -H 'Content-Type: application/json'
```

→ Write `neutralize.fields` + `neutralize.success`.

### A3. Content Gate - "Where do menus/permissions come from?"

```bash
grep -rhoaE '"/api[^"]*(permission|perm|role|menu|acl|resource|nav)[^"]*"' js | sort -u
grep -rhoaE '.{0,30}(menus|permissions|menuList|routeList|authList|role_permissions)\b.{0,120}' js | head
grep -rhoaE 'userRouteAuth|getResultTree|routeMap|routeLink|hasPermission|checkAuth' js | head
grep -rhoaE '([A-Z_][A-Z0-9_]*):\{name:"[^"]*",link:"/[^"]+"\}' js | head
```

**Two layers of data** (common enterprise backend):

| API | Typical payload | Consumer |
|---|---|---|
| `.../role_permissions` | `{ permissions: string[], role_type }` | Route Guard, Button Level ACL |
| `.../permissions/all` | `tree[{ code, position, children }]` | Sidebar menu rendering |
| bundle `userRouteAuth` | `{ CODE: { url, name? } }` | code → front-end path |
| `routeMap` in bundle | `{ KEY: { name, link } }` | Alias ​​resolution (webpack `o.DASHBOARD`) |

Read consumer code confirmation: `getResultTree(tree, permissions)` how to filter, `v-if` / `hasAuth(code)` which field to check.

**Manual forge** (small site): Build permissive payload → `stubs`.

**Full permission tree restoration** (large site, sidebar/submodule still blank): see **Section I**.

---

## B. config.json template

```json
{
  "baseUrl": "https://target/",
  "runtimeMode": "both",
  "chromium": "/usr/bin/chromium",

  "cookies": [
    { "name": "auth", "value": "b64json:{\"id\":1,\"username\":\"admin\",\"role\":\"admin\",\"func\":{},\"permissions\":[\"*\"]}" }
  ],
  "localStorage": { "token": "faketoken", "isLogin": "1" },

  "neutralize": {
    "fields": ["response_code", "code", "errno", "ret", "status"],
    "success": 0,
    "flags": { "success": true, "message": "ok" }
  },
  "forward": true,
  "loginUrlPattern": "/login",
  "apiPattern": "/api/|/rest/|/graphql",

  "mockTier": "L1+L2",
  "recordDetail": true,
  "observe": {
    "storageReads": false,
    "cookieReads": false,
    "xhrHeaders": true
  },
  "neutralizeVueRouter": true,
  "stubs": [
    {
      "match": "permissions/all|/menu|role_permissions",
      "body": {
        "response_code": 0, "code": 0,
        "data": {
          "permissions": ["*"],
          "menus": [
            { "name": "dashboard", "path": "/dashboard", "show": true, "children": [] },
            { "name": "alert", "path": "/alert", "show": true, "children": [] }
          ]
        }
      }
    }
  ],

  "explore": {
    "clickTabs": true,
    "clickTables": true,
    "pushStateFallback": true,
    "maxMenuItems": 50
  },

  "routes": ["/dashboard", "/alert", "/asset", "/device", "/report", "/config", "/system"],
  "waitMs": 1500, "perRouteMs": 900, "headless": true,
  "waitUntil": "domcontentloaded",
  "routeTimeout": 12000,
  "proxy": "",

  "captureResponses": true, "recordWs": true, "respMax": 600
}
```

Field description:
- `runtimeMode`：`depth`（Puppeteer）、`coverage`（browser MCP）、`both`
- `cookies[].value` prefix: `b64json:` → base64(JSON); `json:` → original JSON; no prefix → literal
- `forward: true` forwards the real request and rewrites the code field; `false` is completely offline stub
- `mockTier`: coverage mode preload enable level, such as `L1+L2`, `L1+L2+L3`
- `routes` comes from `routes.txt`; after the forge menu, the harness automatically adds `<a href>`
- `captureResponses` / `recordWs` is only valid in depth mode
- `waitUntil`: Use `domcontentloaded` for large SPA to avoid hang of `networkidle2`
- `routeTimeout`: Single route `page.goto` timeout (milliseconds)
- `proxy`: Puppeteer `--proxy-server`; also available as `HTTP_PROXY` / `HTTPS_PROXY`

### B1. Double stub template (role_permissions + permissions/all)

```json
"stubs": [
  {
    "match": "role_permissions",
    "body": {
      "response_code": 0,
      "data": {
        "permissions": ["MONITOR", "MONITOR_ALERT", "THREAT", "ASSETS_RISK"],
        "role_type": "SUPER_ADMIN"
      }
    }
  },
  {
    "match": "permissions/all",
    "body": {
      "response_code": 0,
      "data": [
        {
          "code": "MONITOR",
          "position": 1,
          "children": [
            { "code": "MONITOR_ALERT", "position": 1, "children": [] }
          ]
        }
      ]
    }
  }
]
```

The outer field name (`response_code` / `code` / `data`) must be consistent with the A2 interceptor gate; `permissions` must cover all leaf codes in the tree.

---

## C. coverage mode: preload configuration

Edit the `scripts/preload.js` top `CONFIG` object, or replace via CDP before injecting:

```javascript
const CONFIG = {
  loginPathRe: /\/(login|signin)(\/|$|\?)/i,
  mockTier: 'L1+L2',
  forward: true,
  recordDetail: true,
  extractUrlsFromResponse: true,
  neutralizeVueRouter: true,
  observe: { storageReads: false, cookieReads: false, xhrHeaders: true },
  neutralize: { fields: ['response_code', 'code'], success: 0 },
  stubs: [ /* 同 config.json stubs */ ],
  apiPattern: /\/(api|apis|v\d+|dev|internal|graphql)\//i,
};
```

Verification: `window.__API_RECON_PRELOAD__ === true` and pathname are stable.

Export recording results:

```javascript
JSON.stringify({
  apis: [...window.__API_RECON_LOG__],
  detail: window.__API_RECON_DETAIL__,
  routes: [...(window.__API_RECON_ROUTES__ || [])],
  observe: window.__API_RECON_OBSERVE__,
}, null, 2)
```

---

## D. preload / runtime Hook capability

Built-in browser Hook capabilities and coverage of preload (coverage) and runtime_harvest (depth):

| Hook capabilities | Value for API discovery | Coverage |
|---|---|---|
| Hook fetch / XHR.open | Fetch request URL/method | ✅ `recordDetail` + `__API_RECON_LOG__` |
| Hook XHR.setRequestHeader | Found Authorization and other headers | ✅ `observe.xhrHeaders` |
| Hook localStorage/cookie read | Confirm session key name | ⚠️ Optional `observe.storageReads/cookieReads` |
| Vue gets routes | Complete frontendRoutes | ✅ `__API_RECON_ROUTES__` (route loaded) |
| Vue route guard neutralization / login jump blocking | Open module trigger API | ✅ `neutralizeVueRouter` + native jump neutralization |
| React gets route | Supplements route | ⚠️ Static + click; no dedicated Hook |
| Page jump blocking (login path) | Leave page analysis | ⚠️ Only block the login path to avoid blocking business navigation |
| Hook encryption library (CryptoJS/SM, etc.) | Encryption parameters → plain text API body | ❌ Parameters must be entered into the Hook encryption function manually; the conclusion is written in config |
| Anti-debugging bypass | Otherwise, the runtime cannot record the API | ❌ Must be processed manually; static is still available |

---

## E. Endpoint extracts regular rules (when there are too few statics)

Relax in `harvest_static.py` by `extract_endpoints`, or manually:

```bash
grep -rhoaE '"/[a-z][A-Za-z0-9_/\-]{3,}"' js | sort -u
grep -rhoaE '/api/[a-zA-Z0-9_./-]+' js | sort -u
```

---

## F. Troubleshooting

| Phenomenon | Cause → Solution |
|---|---|
| Little static API | endpoint dialect mismatch → relax regex (section D) |
| Number of chunks ≪ manifest | CSS-only or chunk not deployed; 404 Retried |
| The runtime still displays the login page | Rendering gate error → Review A1: key name, container, encoding, domain |
| Enter the shell but the module is blank | Content door → forge menu (A3); `routes` path may be wrong |
| Each route only has bootstrap/locale | Incomplete permission code → Section I permission tree restoration; check `role_permissions` + `permissions/all` double stub |
| There are items in the sidebar but the subpage is blank | The tree is missing the intermediate node or the code is inconsistent with `userRouteAuth` |
| Each API jumps to login | Interceptor gate → Confirm `neutralize`; nested fields need to expand walk logic |
| WS frame is 0 | User interaction is required before subscribe; lengthened `perRouteMs` |
| Response body is empty | Only `forward: true` has a real response |
| Chromium is missing | Install chromium or set up `config.chromium` / `CHROMIUM` |
| Mock many still log in | Hook too late or missing `location.href` setter → document-start + preload |
| The list is all empty | L3 empty array is normal; continue to click Tab/Settings/Details |
| Mistake Redux action as route | Filter internal path containing get/set/change/clear/toggle/upload |
| Vue still skips login | preload is not document-start → change the injection timing; or manually clear the guard at `neutralizeVueRouter: false` |
| There is a URL in the response but not logged | Open `extractUrlsFromResponse`; or manually extract it from `__API_RECON_DETAIL__` |
| Don’t know the Authorization header name | Open `observe.xhrHeaders` or DevTools to view the request header |
| runtime extremely slow/timeout | Change `waitUntil: domcontentloaded`; downgrade `routeTimeout`; do not use `networkidle2` |
| Agent connection failed | Check `proxy`/environment variables; Puppeteer and curl proxy ports are consistent |

---

## G. hardened target

The runtime would get stuck at the shell while the server was gradually verifying the session (signed cookies that were not forgeable, menus that were server-rendered and not stubable). Expected behavior:

- **static enough to do endpoint enumeration** — module path in code
- If authorization allows, run the same harness with **real session**: `forward: true`, no need to neutralize, capture real methods/params/responses

---

## H. Single task list

1. Confirm authorization scope
2. **Read** `scripts/harvest_static.py` → Adjust to target → Run → Review `api_static.txt`, `routes.txt`
3. **Phase 1b**: path anchor window expansion + binding layer → `param_candidates.json` (section J)
4. Reverse A1/A2/A3 → write site exclusive `config.json`
5. **Read and adjust** `runtime_harvest.js` / `preload.js` before executing
6. `runtimeMode=depth`: `npm install` → run adjusted harvest script
7. `runtimeMode=coverage/both`: document-start injects adjusted preload → browser MCP dynamic enumeration + **parameter trigger matrix**
8. Module does not render → **Section I permission tree restoration** → patch stubs → rerun
9. Parametric multi-sample diff + error inversion → `params_merged.json`
10. Merge → `site_map.json` + `api_merged.txt`, honestly mark coverage, gaps and script changes

---

## I. Permission tree restoration (Phase 4 deepening)

Used when forge simple `menus: [{ path, show: true }]` is invalid and the submodule is still not mounted.

### I1. Locate the auth module

```bash
grep -l 'userRouteAuth' js/*.js
grep -l 'routeMap\|routeLink' js/*.js
grep -rhoaE 'getResultTree|role_permissions|permissions/all' js | head
```

Records: **Permission API path**, **Response field name**, **Consumption chunk file name**.

### I2. Extract routeMap

```bash
python3 scripts/extract_route_map.py recon/js recon/
# 产出 recon/route_map.json
```

If `[!] no routeMap pattern found`: Relax the regular rules in `extract_route_map.py`, or manually grep:

```bash
grep -rhoaE '([A-Z_][A-Z0-9_]*):\{name:"[^"]*",link:"/[^"]+"\}' js | head -20
```

### I3. Build permission tree + stub

```bash
python3 scripts/build_perm_tree.py recon/js recon/ --config recon/config.json
```

Script logic:
1. Parse `userRouteAuth={MONITOR:{url:...},...}` (including webpack alias `He=o.DASHBOARD`)
2. Use `route_map.json` to parse alias → real path
3. Infer parent by code prefix (`MONITOR_ALERT` → `MONITOR`)
4. Output `permissions_tree.json`, `permissions_all_stub.json`, `role_permissions_stub.json`
5. `--config` automatically writes `config.json`’s `stubs` and extension `routes`

**Adjust by Target** (at top of script):
- `DEFAULT_ROOTS`: top module code list
- `DEFAULT_PREFIX_PARENT`: `PREFIX_` → parent mapping
- `DEFAULT_EXTRA_PARENT`: orphan node with non-prefix relationship

### I4. Verify stub consistency

```bash
# permissions 数量应 ≈ userRouteAuth 条目数
wc -l recon/perm_codes_all.txt
# routes 应覆盖 route_map 全部 link
python3 -c "import json; m=json.load(open('recon/route_map.json')); r=set(json.load(open('recon/config.json'))['routes']); print('missing', [v['link'] for v in m.values() if v['link'] not in r])"
```

### I5. Rerun the runtime and compare

```bash
node recon/runtime_harvest.js recon/config.json
# 对比 forge 前后 runtime_api.json 条数；检查 /attack、/asset 等是否出现模块 API
```

| before forge | after forge (success) |
|---|---|
| Each route has the same 3–5 bootstraps | Different routes trigger different module APIs |
| `/api/locale/language` only | `/api/web/...` module endpoint appears |
| `routes.txt` single digit route | `routes` 80–110+ from route_map |

### I6. Still fails

- **coverage mode**: click sidebar + Tab, permission gating may be requested after interaction
- **stub field**: Compare real API (curl + real session) and stub nesting
- **Extra Guards**: grep `hasPermission|checkRole|func.` and other button-level checks, extend `role_permissions.permissions`
- **static bottom line**: module API path is still in `api_static.txt`, runtime only adds METHOD/body; parameters are retained in `param_candidates.json` + recorded samples

---

## J. Parameter reverse engineering (Phase 1b/5b/5c)

**Methodology, non-universal script. ** Use regular rules to find path; use anchor window expansion + UI binding chain + multi-sample diff + error inversion to find parameters.

### J1. Anchor point window expansion — find package objects from path

```bash
# 以 Phase 1 已知 path 为锚
grep -n '"/api/user/list"' js/*.js
grep -rhoaE '.{0,120}("/api[^"]+").{0,200}' js | head
grep -rhoaE '(params|data|body|payload)\s*:\s*\{' js | head
grep -rhoaE '(get|post|put|delete|patch)\([^,]+,\s*\{' js | head
```

### J2. Packaging layer and transmission form

```bash
# axios / 统一 request
grep -rhoaE '(axios|request)\.(get|post|put|delete|patch)\(' js | head
grep -rhoaE 'interceptors\.(request|response)' js | head

# GraphQL
grep -rhoaE '(query|mutation)\s+\w+|gql`|graphql\(' js | head
grep -rhoaE '\$[a-zA-Z_]+\s*:\s*(Int|String|Boolean|\[)' js | head

# FormData / multipart
grep -rhoaE 'FormData|\.append\(' js | head

# 路径参数
grep -rhoaE 'path:\s*"/[^"]*:[^"]+"' js | head
grep -rhoaE 'useParams|route\.params|\$route\.params' js | head
```

### J3. Validation Gate — Required / Format / Enumeration

```bash
grep -rhoaE '(required|message|pattern|enum|validator)\s*:' js | head
grep -rhoaE 'yup\.|zod\.|async-validator|Form\.Item|a-form-item|el-form-item' js | head
grep -rhoaE 'rules\s*:\s*\[|name:\s*["\'][a-zA-Z_]+["\']' js | head
grep -rhoaE 'label.*value|options\s*:\s*\[' js | head
```

### J4. Binding layer — Form → API

```bash
grep -rhoaE 'onFinish|handleSubmit|getFieldsValue|validateFields' js | head
grep -rhoaE '(pick|omit|transform|dayjs|moment)\(' js | head
```

Runtime complement: DevTools → Network → Request → **Initiate program** (call stack) to chase up the package function from `fetch`/`send`.

### J5. Encryption parameters

```bash
grep -rhoaE 'encrypt|decrypt|sign|CryptoJS|sm2|sm3|sm4|RSA|AES' js | head
```

**Do not guess the fields on the ciphertext** — Hook encryption function **Input parameters**, record the plaintext payload before encryption; write the conclusion `config.json` / `param_candidates.json`.

### J6. Parameter trigger matrix (must do in Phase 3)

Record each module once per operation, diff request body/query:

| Operation | Follow |
|---|---|
| List first screen | Paging default value |
| Search | keyword, filters |
| Advanced filtering | optional fields |
| New/Edit | Complete entity |
| Batch/Export | `ids[]`, `exportType` |
| Sort/Page | `sortField`, `order` |

Output `param_samples.json`: `[{ "path", "method", "action": "search", "body", "query", "headers" }]`

### J7. Confidence rules

| Confidence | Conditions |
|---|---|
| **High** | Static callsite + runtime ≥2 samples consistent |
| **Medium** | Static only, or only 1 runtime |
| **Low** | Response/error backcast, no secondary verification |
| **To be triggered** | Static known fields, UI/permissions have not been reached |

### J8. Quick scene matching

| Scene | Sequence |
|---|---|
| REST list page | J1 package object → J6 four times diff → J3 rules |
| New/edit form | J3 Form name → J4 submit chain → runtime submission + intentionally left blank to see 400 |
| GraphQL | J2 variables declaration → runtime operation record variables |
| Encrypted body | J5 Hook input parameters → The fields before encryption are real params |

### J9. Mapping with api-recon stage

| api-recon | parameter recon |
|---|---|
| Phase 1 static | J1 anchor point window expansion |
| Phase 2 A2 interceptor | Global injection fields (tenantId, sign) |
| Phase 3 runtime | J6 trigger matrix + `param_samples.json` |
| Phase 4 Permission Tree | Different modules have different forms → Only with sufficient permissions can all fields be triggered |
| Phase 5 Merge | `params_merged.json` + Confidence; Do not specify a single sample. Required |

### J10. Troubleshooting

| Phenomenon | Treatment |
|---|---|
| The static field name runtime never appears | Mark "to be triggered"; make up the permission tree / click advanced filter / linkage to select each option |
| Same path but different body shape | Normal - separate records according to `action`, do not forcibly merge schema |
| The stub response is false but you want to see params | **Look at the outbound request** body/headers, do not infer from the stub response |
| 400 reported nested field | Pay attention to the outer packaging `data`/`bizData`/`variables` |
| GraphQL only sees operation name | Expand `variables` JSON; statically find `$var: Type` |

---
