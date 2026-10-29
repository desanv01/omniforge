#include "owned_slot.h"
#include <intrin.h>
#include <string.h>
#include <wchar.h>

_Static_assert(sizeof(HANDLE) == 8, "x64 HANDLE required");
_Static_assert(sizeof(WCHAR) == 2 && sizeof(DWORD) == 4, "Windows widths required");
_Static_assert(__alignof(OF_SLOT) == 8, "slot alignment contract");
_Static_assert(offsetof(OF_SLOT, arena) % 8 == 0, "attribute arena alignment");
_Static_assert(sizeof(OF_SLOT) <= OF_SLOT_CAPACITY, "fixed slot capacity exceeded");
_Static_assert(OF_RECORDS < UINT64_MAX, "finite history");
_Static_assert(OF_NORMAL_RECORDS + OF_CLEANUP_RECORDS <= OF_RECORDS, "separate cleanup capacity");
_Static_assert(8u + 8u + 8u + 1u <= OF_CLEANUP_RECORDS, "destruction and final observation reserves");

static int aligned(const void *p) { return p && ((uintptr_t)p % 8u) == 0; }
static int take(OF_SLOT *s) { return _InterlockedCompareExchange(&s->guard, 1, 0) == 0; }
static void release(OF_SLOT *s) { (void)_InterlockedExchange(&s->guard, 0); }
static int same_id(const OF_ID *a, const OF_ID *b) {
    return a->role == b->role && memcmp(a->operation, b->operation, 16) == 0 &&
           memcmp(a->generation, b->generation, 16) == 0;
}
static int valid_id(const OF_ID *id) {
    unsigned int i, a = 0, b = 0;
    if (!id || id->role < 1 || id->role > 3) return 0;
    for (i = 0; i < 16; ++i) { a |= id->operation[i]; b |= id->generation[i]; }
    return a != 0 && b != 0;
}
static int valid_api(const OF_API *a) {
    return a && a->job && a->limits_set && a->query && a->file && a->handle_info &&
        a->attr_init && a->attr_update && a->attr_delete && a->process && a->member &&
        a->resume && a->terminate && a->wait && a->exit_code && a->close &&
        a->error_get && a->error_set;
}
static int owned(const OF_SLOT *s, unsigned int index) {
    return index < OF_HANDLE_COUNT && s->life[index] == OF_OPEN && s->handles[index] != NULL;
}
static void clear_error(OF_SLOT *s) { s->api->error_set(0); }
static void failed(OF_SLOT *s, OF_RESULT *r) { r->error = s->api->error_get(); r->code = OF_FAILED; }
static int inheritance(OF_SLOT *s, HANDLE h, DWORD expected, OF_RESULT *r) {
    DWORD flags = 0; BOOL ok;
    clear_error(s); ok = s->api->handle_info(h, &flags);
    if (!ok) { failed(s, r); return 0; }
    if (flags != expected) { r->code = OF_FAILED; return 0; }
    return 1;
}
static void publish(OF_SLOT *s, unsigned int index, HANDLE h) {
    unsigned int i;
    if (h && h != INVALID_HANDLE_VALUE) for (i = 0; i < OF_HANDLE_COUNT; ++i)
        if (i != index && s->life[i] == OF_OPEN && s->handles[i] == h) s->uncertain = 1;
    s->handles[index] = h;
    if (h && h != INVALID_HANDLE_VALUE) s->life[index] = OF_OPEN;
}
static int text_length(const WCHAR *text, size_t capacity, size_t *length) {
    size_t i;
    for (i = 0; i < capacity; ++i) {
        if (!text[i]) { *length = i; return 1; }
        if (text[i] < 32) return 0;
    }
    return 0;
}
static int absolute(const WCHAR *text, size_t n) {
    return n >= 3 && ((text[0] >= L'A' && text[0] <= L'Z') ||
        (text[0] >= L'a' && text[0] <= L'z')) && text[1] == L':' && text[2] == L'\\';
}
static int suffix(const WCHAR *text, size_t n, const WCHAR *end) {
    size_t k = wcslen(end);
    return n > k && text[n-k-1] == L'\\' && wmemcmp(text+n-k, end, k) == 0;
}
static int launch_valid(const OF_LAUNCH *p) {
    size_t a, b, d, e;
    return p && p->target >= OF_DUMMY_WAIT && p->target <= OF_DUMMY_SETTLEMENT &&
        text_length(p->interpreter, 512, &a) && absolute(p->interpreter, a) && suffix(p->interpreter, a, L"python.exe") &&
        text_length(p->script, 512, &b) && absolute(p->script, b) && suffix(p->script, b, L"windows_process_dummy.py") &&
        text_length(p->directory, 512, &d) && absolute(p->directory, d) &&
        text_length(p->system_root, 512, &e) && (e == 0 || absolute(p->system_root, e));
}
static int same_launch(const OF_LAUNCH *a, const OF_LAUNCH *b) {
    return launch_valid(b) && a->target == b->target &&
        wcscmp(a->interpreter, b->interpreter) == 0 && wcscmp(a->script, b->script) == 0 &&
        wcscmp(a->directory, b->directory) == 0 && wcscmp(a->system_root, b->system_root) == 0;
}
static int put(WCHAR *out, size_t cap, size_t *used, WCHAR ch) {
    if (*used + 1 >= cap) return 0;
    out[(*used)++] = ch; out[*used] = 0; return 1;
}
static int append(WCHAR *out, size_t cap, size_t *used, const WCHAR *text) {
    for (; *text; ++text) if (!put(out, cap, used, *text)) return 0;
    return 1;
}
static int quote(WCHAR *out, size_t cap, size_t *used, const WCHAR *text) {
    size_t slashes, i;
    if (!put(out, cap, used, L'"')) return 0;
    while (*text) {
        slashes = 0;
        while (*text == L'\\') { ++slashes; ++text; }
        if (*text == L'"' || !*text) slashes *= 2;
        for (i = 0; i < slashes; ++i) if (!put(out, cap, used, L'\\')) return 0;
        if (!*text) break;
        if (*text == L'"' && !put(out, cap, used, L'\\')) return 0;
        if (!put(out, cap, used, *text++)) return 0;
    }
    return put(out, cap, used, L'"');
}
static int launch_buffers(OF_SLOT *s) {
    size_t used = 0, env = 0;
    const WCHAR *mode = s->launch.target == OF_DUMMY_WAIT ? L" dummy_wait" :
        s->launch.target == OF_DUMMY_TREE ? L" dummy_tree" : L" dummy_settlement";
    s->command[0] = 0; s->environment[0] = 0;
    if (!quote(s->command, 4096, &used, s->launch.interpreter) ||
        !append(s->command, 4096, &used, L" -I -S -B ") ||
        !quote(s->command, 4096, &used, s->launch.script) ||
        !append(s->command, 4096, &used, mode)) return 0;
    if (s->launch.system_root[0] &&
        (!append(s->environment, 1024, &env, L"SystemRoot=") ||
         !append(s->environment, 1024, &env, s->launch.system_root))) return 0;
    if (!put(s->environment, 1024, &env, 0) || !put(s->environment, 1024, &env, 0)) return 0;
    return 1;
}

int of_slot_init(OF_SLOT *s, size_t capacity, const OF_ID *id, const OF_API *api) {
    size_t i; const unsigned char *bytes; int code = OF_INVALID;
    if (!aligned(s) || capacity < sizeof(*s) || !valid_id(id) || !valid_api(api)) return OF_INVALID;
    if (!take(s)) return OF_BUSY;
    if (s->magic == OF_MAGIC && s->version == OF_VERSION) {
        code = same_id(&s->id, id) && s->api == api ? OF_OK : OF_INVALID;
        release(s); return code; /* idempotent, NEVER resets a live or closed ledger */
    }
    bytes = (const unsigned char *)s;
    /* Guard is already one; all remaining fresh caller storage must be zero. */
    for (i = sizeof(s->guard); i < sizeof(*s); ++i) if (bytes[i] != 0) { release(s); return OF_INVALID; }
    s->id = *id; s->api = api; s->next_sequence = 1;
    s->version = OF_VERSION; s->magic = OF_MAGIC;
    release(s); return OF_OK;
}

static void execute(OF_SLOT *s, const OF_REQUEST *q, OF_RESULT *r) {
    BOOL ok, is_member; DWORD flags, used, value; HANDLE h; SIZE_T size;
    SECURITY_ATTRIBUTES sa; JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting; STARTUPINFOEXW startup;
    LPPROC_THREAD_ATTRIBUTE_LIST attr = (LPPROC_THREAD_ATTRIBUTE_LIST)s->arena;
    unsigned int i, resource = q->index;
    r->code = OF_INVALID;
    if (s->blocked && q->action != OF_TERMINATE && q->action != OF_WAIT &&
        q->action != OF_ACTIVE && q->action != OF_EXIT && q->action != OF_ATTR_DELETE &&
        q->action != OF_CLOSE) return;
    switch (q->action) {
    case OF_JOB:
        if (q->index || q->parameter || s->acquire_attempt[0]) return;
        s->acquire_attempt[0] = 1;
        clear_error(s); h = s->api->job(NULL, NULL); /* acquire and publish in C */
        publish(s, 0, h); r->raw = (uint64_t)(uintptr_t)h;
        if (!h) { failed(s, r); return; }
        if (h == INVALID_HANDLE_VALUE) { s->uncertain = 1; r->code = OF_UNKNOWN; return; }
        if (!inheritance(s, h, 0, r)) return;
        r->code = OF_OK; return;
    case OF_LIMIT_SET:
        if (q->index || q->parameter != OF_KILL_ON_CLOSE || !owned(s, 0) || s->limit_attempt) return;
        s->limit_attempt = 1; memset(&limits, 0, sizeof(limits));
        limits.BasicLimitInformation.LimitFlags = OF_KILL_ON_CLOSE;
        clear_error(s); ok = s->api->limits_set(s->handles[0], JobObjectExtendedLimitInformation, &limits, (DWORD)sizeof(limits));
        r->raw = (uint64_t)(unsigned int)ok;
        if (!ok) { failed(s, r); return; } r->code = OF_OK; return;
    case OF_LIMIT_GET:
        if (q->index || q->parameter || !owned(s, 0)) return;
        memset(&limits, 0, sizeof(limits)); used = 0;
        clear_error(s); ok = s->api->query(s->handles[0], JobObjectExtendedLimitInformation, &limits, (DWORD)sizeof(limits), &used);
        if (!ok) { failed(s, r); return; }
        if (used != sizeof(limits)) { s->uncertain = 1; r->code = OF_UNKNOWN; return; }
        r->value = limits.BasicLimitInformation.LimitFlags;
        s->limits_verified = r->value == OF_KILL_ON_CLOSE;
        r->code = s->limits_verified ? OF_OK : OF_FAILED; return;
    case OF_STANDARD:
        if (q->index >= 3 || q->parameter) return;
        resource = q->index + 1;
        if (s->acquire_attempt[resource]) return;
        s->acquire_attempt[resource] = 1;
        memset(&sa, 0, sizeof(sa)); sa.nLength = (DWORD)sizeof(sa); sa.bInheritHandle = TRUE;
        clear_error(s); h = s->api->file(L"NUL", q->index == 0 ? GENERIC_READ : GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        r->raw = (uint64_t)(uintptr_t)h;
        if (h == INVALID_HANDLE_VALUE) { failed(s, r); return; }
        publish(s, resource, h);
        if (!h) { s->uncertain = 1; r->code = OF_UNKNOWN; return; }
        if (!inheritance(s, h, HANDLE_FLAG_INHERIT, r)) return;
        r->code = OF_OK; return;
    case OF_ATTR_INIT:
        if (q->index || q->parameter || s->attr_attempt) return;
        s->attr_attempt = 1; size = 0;
        clear_error(s); ok = s->api->attr_init(NULL, 2, 0, &size);
        flags = !ok ? s->api->error_get() : 0;
        r->raw = (uint64_t)(unsigned int)ok; r->error = flags;
        if (ok || flags != ERROR_INSUFFICIENT_BUFFER || !size || size > OF_ARENA_CAPACITY) {
            s->attr_life = OF_ATTR_INIT_FAILED; r->code = OF_FAILED; return;
        }
        s->attr_size = size; s->attr_life = OF_ATTR_INITIALIZING;
        clear_error(s); ok = s->api->attr_init(attr, 2, 0, &s->attr_size);
        r->raw = (uint64_t)(unsigned int)ok;
        if (!ok) { failed(s, r); s->attr_life = OF_ATTR_INIT_FAILED; return; }
        s->attr_life = OF_ATTR_READY; r->code = OF_OK; return;
    case OF_ATTR_UPDATE:
        if (q->index > 1 || q->parameter || s->attr_life != OF_ATTR_READY || s->attr_update_attempt[q->index]) return;
        if (!owned(s, 0)) return;
        for (i = 1; i <= 3; ++i) if (!owned(s, i)) return;
        s->attr_update_attempt[q->index] = 1;
        s->job_values[0] = s->handles[0];
        if (q->index == 1) for (i = 0; i < 3; ++i) s->standard_values[i] = s->handles[i+1];
        clear_error(s); ok = s->api->attr_update(attr, 0,
            q->index == 0 ? PROC_THREAD_ATTRIBUTE_JOB_LIST : PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            q->index == 0 ? (PVOID)s->job_values : (PVOID)s->standard_values,
            q->index == 0 ? sizeof(s->job_values) : sizeof(s->standard_values), NULL, NULL);
        r->raw = (uint64_t)(unsigned int)ok;
        if (!ok) { failed(s, r); return; } r->code = OF_OK; return;
    case OF_PROCESS:
        if (q->index || q->parameter != OF_CREATION_FLAGS || s->process_attempt || !launch_valid(q->launch) ||
            !s->limits_verified || s->attr_life != OF_ATTR_READY || !s->attr_update_attempt[0] || !s->attr_update_attempt[1]) return;
        for (i = 0; i <= 3; ++i) if (!owned(s, i)) return;
        s->process_attempt = 1; s->launch = *q->launch;
        s->root_signaled = 0; s->zero_active_observed = 0; /* pre-create queries cannot prove this tree empty */
        if (!launch_buffers(s)) return;
        memset(&startup, 0, sizeof(startup)); startup.StartupInfo.cb = (DWORD)sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = s->handles[1]; startup.StartupInfo.hStdOutput = s->handles[2]; startup.StartupInfo.hStdError = s->handles[3];
        startup.lpAttributeList = attr;
        clear_error(s); ok = s->api->process(s->launch.interpreter, s->command, NULL, NULL, TRUE,
            OF_CREATION_FLAGS, s->environment, s->launch.directory, &startup.StartupInfo, &s->process_info);
        /* C-owned outputs exist independent of any later Python projection. */
        publish(s, OF_PROCESS_HANDLE, s->process_info.hProcess);
        publish(s, OF_THREAD_HANDLE, s->process_info.hThread);
        s->process_possible = ok || s->process_info.hProcess || s->process_info.hThread;
        r->raw = (uint64_t)(unsigned int)ok;
        if (!ok) { failed(s, r); if (s->process_possible) s->uncertain = 1; return; }
        if (!owned(s, OF_PROCESS_HANDLE) || !owned(s, OF_THREAD_HANDLE)) { s->uncertain = 1; r->code = OF_UNKNOWN; return; }
        if (!inheritance(s, s->handles[4], 0, r) || !inheritance(s, s->handles[5], 0, r)) return;
        r->code = OF_OK; return;
    case OF_MEMBER:
        if (q->index || q->parameter || !owned(s, 0) || !owned(s, 4)) return;
        is_member = FALSE; clear_error(s); ok = s->api->member(s->handles[4], s->handles[0], &is_member);
        if (!ok) { failed(s, r); return; }
        s->member_verified = is_member != FALSE; r->value = (uint64_t)(unsigned int)is_member;
        r->code = s->member_verified ? OF_OK : OF_FAILED; return;
    case OF_RESUME:
        if (q->index || q->parameter || s->resume_attempt || !s->member_verified || !owned(s, 5)) return;
        s->resume_attempt = 1;
        clear_error(s); value = s->api->resume(s->handles[5]); r->raw = value;
        if (value == MAXDWORD) { failed(s, r); s->uncertain = 1; return; }
        if (value != 1) { s->uncertain = 1; r->code = OF_UNKNOWN; return; }
        r->code = OF_OK; return;
    case OF_TERMINATE:
        if (q->index || q->parameter || s->terminate_attempt || !owned(s, 0)) return;
        s->terminate_attempt = 1;
        clear_error(s); ok = s->api->terminate(s->handles[0], 0xD1A6u);
        if (!ok) { failed(s, r); s->uncertain = 1; return; } r->code = OF_OK; return;
    case OF_WAIT:
        if (q->index || q->parameter || !owned(s, 4)) return;
        clear_error(s); value = s->api->wait(s->handles[4], 0); r->raw = value;
        if (value == WAIT_OBJECT_0) { s->root_signaled = 1; r->code = OF_OK; return; }
        if (value == WAIT_TIMEOUT) { r->code = OF_OK; return; }
        if (value == WAIT_FAILED) failed(s, r); else r->code = OF_UNKNOWN;
        s->uncertain = 1; return;
    case OF_ACTIVE:
        if (q->index || q->parameter || !owned(s, 0)) return;
        memset(&accounting, 0, sizeof(accounting)); used = 0;
        clear_error(s); ok = s->api->query(s->handles[0], JobObjectBasicAccountingInformation, &accounting, (DWORD)sizeof(accounting), &used);
        if (!ok) { failed(s, r); s->uncertain = 1; return; }
        if (used != sizeof(accounting)) { s->uncertain = 1; r->code = OF_UNKNOWN; return; }
        r->value = accounting.ActiveProcesses; s->zero_active_observed = accounting.ActiveProcesses == 0;
        r->code = OF_OK; return;
    case OF_EXIT:
        if (q->index || q->parameter || !s->root_signaled || !owned(s, 4)) return;
        value = 0; clear_error(s); ok = s->api->exit_code(s->handles[4], &value);
        if (!ok) { failed(s, r); s->uncertain = 1; return; }
        r->value = value; r->code = OF_OK; return;
    case OF_ATTR_DELETE:
        if (q->index || q->parameter || s->attr_delete_attempt || s->attr_life != OF_ATTR_READY) return;
        s->attr_delete_attempt = 1; s->attr_life = OF_ATTR_DESTROYING;
        s->api->attr_delete(attr); /* no Python callback/check between return and state */
        s->attr_life = OF_ATTR_DESTROYED; r->code = OF_OK; return;
    case OF_CLOSE:
        if (q->parameter || resource >= OF_HANDLE_COUNT || s->close_attempt[resource] || !owned(s, resource)) return;
        if (s->attr_life == OF_ATTR_READY || s->attr_life == OF_ATTR_INITIALIZING || s->attr_life == OF_ATTR_DESTROYING) return;
        if ((resource == 0 || resource >= 4) && s->process_possible && (!s->root_signaled || !s->zero_active_observed)) return;
        if (resource == 0 && !s->zero_active_observed) return;
        for (i = 0; i < OF_HANDLE_COUNT; ++i)
            if (i != resource && s->handles[i] == s->handles[resource] && s->close_attempt[i]) return;
        s->close_attempt[resource] = 1;
        clear_error(s); ok = s->api->close(s->handles[resource]); r->raw = (uint64_t)(unsigned int)ok;
        if (!ok) { failed(s, r); s->life[resource] = OF_CLOSE_FAILED; s->uncertain = 1; return; }
        s->life[resource] = OF_CLOSED; r->code = OF_OK; return;
    default: return;
    }
}

/* Eight dedicated once-actions: terminate, attr-delete, six closes. Final
 * observations have disjoint 8 WAIT, 8 ACTIVE and 1 EXIT credits. Ordinary history
 * cannot consume these credits. Invalid/duplicate cleanup is refused unrecorded. */
static int budget(OF_SLOT *s, const OF_REQUEST *q, unsigned int *bucket) {
    unsigned int limit = 1;
    *bucket = OF_CLEANUP_BUCKETS; /* normal */
    if (q->action == OF_TERMINATE) {
        if (q->index || q->parameter || !owned(s, 0) || s->terminate_attempt) return OF_INVALID;
        *bucket = 0;
    } else if (q->action == OF_ATTR_DELETE) {
        if (q->index || q->parameter || s->attr_life != OF_ATTR_READY || s->attr_delete_attempt) return OF_INVALID;
        *bucket = 1;
    } else if (q->action == OF_CLOSE) {
        if (q->parameter || q->index >= OF_HANDLE_COUNT || !owned(s, q->index) || s->close_attempt[q->index]) return OF_INVALID;
        if (s->attr_life == OF_ATTR_READY || s->attr_life == OF_ATTR_INITIALIZING || s->attr_life == OF_ATTR_DESTROYING) return OF_INVALID;
        if ((q->index == 0 || q->index >= 4) && s->process_possible && (!s->root_signaled || !s->zero_active_observed)) return OF_INVALID;
        if (q->index == 0 && !s->zero_active_observed) return OF_INVALID;
        *bucket = 2u + q->index;
    } else if ((s->cleanup_started || (s->normal_count >= OF_NORMAL_RECORDS && !s->process_possible)) &&
               (q->action == OF_WAIT || q->action == OF_ACTIVE || q->action == OF_EXIT)) {
        if (q->index || q->parameter) return OF_INVALID;
        if (q->action == OF_WAIT) {
            if (!owned(s, 4)) return OF_INVALID;
            *bucket = 8; limit = 8;
        } else if (q->action == OF_ACTIVE) {
            if (!owned(s, 0)) return OF_INVALID;
            *bucket = 9; limit = 8;
        } else {
            if (!owned(s, 4) || !s->root_signaled) return OF_INVALID;
            *bucket = 10;
        }
    }
    if (*bucket == OF_CLEANUP_BUCKETS)
        return s->normal_count < OF_NORMAL_RECORDS ? OF_OK : OF_FULL;
    if (s->cleanup_count >= OF_CLEANUP_RECORDS || s->cleanup_uses[*bucket] >= limit) return OF_FULL;
    return OF_OK;
}

int of_slot_apply(OF_SLOT *s, const OF_ID *id, const OF_REQUEST *q, OF_RESULT *out) {
    OF_RECORD *entry; unsigned int i, bucket; int code;
    if (!aligned(s) || !id || !q || !out) return OF_INVALID;
    if (!take(s)) return OF_BUSY;
    if (s->magic != OF_MAGIC || s->version != OF_VERSION || !same_id(&s->id, id)) { release(s); return OF_INVALID; }
    if (!q->sequence || q->sequence == UINT64_MAX || (q->action == OF_PROCESS ? !launch_valid(q->launch) : q->launch != NULL)) {
        release(s); return OF_INVALID;
    }
    for (i = 0; i < s->record_count; ++i) {
        entry = &s->records[i];
        if (entry->sequence != q->sequence) continue;
        if (entry->action != q->action || entry->index != q->index || entry->parameter != q->parameter ||
            (q->action == OF_PROCESS && !same_launch(&s->launch, q->launch))) { release(s); return OF_INVALID; }
        if (!entry->finished) { release(s); return OF_UNKNOWN; }
        *out = entry->result; out->replay = 1; code = (int)out->code; release(s); return code;
    }
    if (q->sequence != s->next_sequence) { release(s); return OF_STALE; }
    if (s->record_count >= OF_RECORDS) { release(s); return OF_FULL; }
    if (q->action == OF_PROCESS && s->launch_sequence) { release(s); return OF_INVALID; }
    code = budget(s, q, &bucket);
    if (code != OF_OK) { release(s); return code; }
    if (bucket == OF_CLEANUP_BUCKETS) ++s->normal_count;
    else { ++s->cleanup_count; ++s->cleanup_uses[bucket]; }
    if (q->action == OF_TERMINATE) { s->cleanup_started = 1; s->blocked = 1; }
    entry = &s->records[s->record_count++];
    entry->sequence = q->sequence; entry->action = q->action;
    entry->index = q->index; entry->parameter = q->parameter;
    ++s->next_sequence; /* finite records never wrap; each attempt permanently retained */
    if (q->action == OF_PROCESS) { s->launch = *q->launch; s->launch_sequence = q->sequence; }
    execute(s, q, &entry->result);
    if (entry->result.code != OF_OK || s->uncertain) s->blocked = 1;
    entry->finished = 1; *out = entry->result; code = (int)out->code;
    release(s); return code;
}

int of_slot_snapshot(OF_SLOT *s, const OF_ID *id, OF_SNAPSHOT *out) {
    unsigned int i;
    if (!aligned(s) || !id || !out) return OF_INVALID;
    if (!take(s)) return OF_BUSY; /* no read of mutable ledger before guard */
    if (s->magic != OF_MAGIC || s->version != OF_VERSION || !same_id(&s->id, id)) { release(s); return OF_INVALID; }
    memset(out, 0, sizeof(*out)); out->id = s->id; out->next_sequence = s->next_sequence;
    out->record_count = s->record_count; out->uncertain = s->uncertain;
    out->normal_count = s->normal_count; out->cleanup_count = s->cleanup_count;
    for (i = 0; i < OF_HANDLE_COUNT; ++i) { out->handles[i] = (uint64_t)(uintptr_t)s->handles[i]; out->life[i] = s->life[i]; }
    out->attr_life = s->attr_life; out->process_possible = s->process_possible;
    out->root_signaled = s->root_signaled; out->zero_active_observed = s->zero_active_observed;
    if (s->record_count) out->last = s->records[s->record_count-1].result;
    release(s); return OF_OK;
}
