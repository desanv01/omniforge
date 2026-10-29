/* SOURCE ONLY: no build/load release. No DllMain, real OS ownership or callbacks. */
#include "slot_inert_exports.h"
#include <intrin.h>
#include <string.h>
#include <wchar.h>

#define OF_FIELD_VALUE(name, value) (uint32_t)(value),
static const uint32_t descriptor[] = {
    0x4942464fu, 1u, OF_INERT_BYTES, OF_INERT_WORDS, 6u, OF_D_COUNT,
    OF_INERT_FIELDS(OF_FIELD_VALUE)
};
#undef OF_FIELD_VALUE
_Static_assert(sizeof(descriptor) == OF_INERT_BYTES, "descriptor size");
_Static_assert(sizeof(int) == sizeof(int32_t), "core return width");
_Static_assert(sizeof(OF_SLOT) == 86424u, "independent opaque slot calculation");
_Static_assert(offsetof(OF_SLOT, arena) == 14744u, "independent arena calculation");
_Static_assert(OF_D_COUNT == 136 && OF_INERT_BYTES == 568u, "fixed v1 wire count");
_Static_assert(sizeof(((OF_SNAPSHOT *)0)->handles) == 6u * sizeof(uint64_t), "snapshot handle array");
_Static_assert(sizeof(((OF_SNAPSHOT *)0)->life) == 6u * sizeof(uint32_t), "snapshot life array");

typedef struct INERT_CONTEXT {
    OF_SLOT *slot;
    const OF_REQUEST *request;
    DWORD error;
} INERT_CONTEXT;
static volatile LONG wrapper_guard;
/* Only accessed while wrapper_guard is owned; never retained after return. */
static INERT_CONTEXT *current;
static int enter(INERT_CONTEXT *ctx) {
    if (_InterlockedCompareExchange(&wrapper_guard, 1, 0) != 0) return 0;
    current = ctx; return 1;
}
static void leave(void) { current = NULL; (void)_InterlockedExchange(&wrapper_guard, 0); }
static int span(const void *p, size_t bytes, uintptr_t alignment) {
    uintptr_t v = (uintptr_t)p;
    return v && v % alignment == 0 && bytes <= UINTPTR_MAX - v;
}
static int separate(const void *a, size_t an, const void *b, size_t bn) {
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x + an <= y || y + bn <= x;
}
static int base(OF_SLOT *s, const OF_ID *id) {
    return span(s, OF_SLOT_CAPACITY, 8u) && span(id, sizeof(*id), 4u) &&
        separate(s, OF_SLOT_CAPACITY, id, sizeof(*id));
}
static int utf16_field(const WCHAR *p) {
    size_t i; int ended = 0;
    for (i = 0; i < 512; ++i) {
        uint32_t c = p[i];
        if (!c) { ended = 1; continue; }
        if (ended || c < 32u) return 0;
        if (c >= 0xD800u && c <= 0xDBFFu) {
            if (i+1u >= 512u || p[i+1u] < 0xDC00u || p[i+1u] > 0xDFFFu) return 0;
            ++i;
        } else if (c >= 0xDC00u && c <= 0xDFFFu) return 0;
    }
    return ended; /* NUL terminated, zero padded, no malformed surrogate input */
}
int32_t __cdecl of_inert_descriptor_v1(void *output, uint32_t bytes) {
    unsigned char *p = output; size_t i;
    if (bytes != OF_INERT_BYTES || !span(output, bytes, 4u)) return OF_INVALID;
    for (i = 0; i < OF_INERT_WORDS; ++i) {
        uint32_t w = descriptor[i];
        p[4u*i] = (unsigned char)w; p[4u*i+1u] = (unsigned char)(w >> 8);
        p[4u*i+2u] = (unsigned char)(w >> 16); p[4u*i+3u] = (unsigned char)(w >> 24);
    }
    return OF_OK;
}

static HANDLE synthetic(unsigned int index) { return (HANDLE)(uintptr_t)(0x100u + index); }
static BOOL bad(void) { current->error = ERROR_INVALID_PARAMETER; return FALSE; }
static DWORD WINAPI fake_error_get(void) { return current->error; }
static VOID WINAPI fake_error_set(DWORD e) { current->error = e; }
static HANDLE WINAPI fake_job(LPSECURITY_ATTRIBUTES sa, LPCWSTR name) {
    if (sa || name) { (void)bad(); return NULL; } return synthetic(0);
}
static BOOL WINAPI fake_limits(HANDLE h, JOBOBJECTINFOCLASS kind, LPVOID data, DWORD bytes) {
    const JOBOBJECT_EXTENDED_LIMIT_INFORMATION *p = data;
    if (h != synthetic(0) || kind != JobObjectExtendedLimitInformation || !p ||
        bytes != sizeof(*p) || p->BasicLimitInformation.LimitFlags != OF_KILL_ON_CLOSE) return bad();
    return TRUE;
}
static BOOL WINAPI fake_query(HANDLE h, JOBOBJECTINFOCLASS kind, LPVOID data, DWORD bytes, LPDWORD used) {
    if (h != synthetic(0) || !data || !used) return bad();
    if (kind == JobObjectExtendedLimitInformation && bytes == sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION *p = data; p->BasicLimitInformation.LimitFlags = OF_KILL_ON_CLOSE;
    } else if (kind == JobObjectBasicAccountingInformation && bytes == sizeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)) {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION *p = data; p->ActiveProcesses = 0;
    } else return bad();
    *used = bytes; return TRUE;
}
static HANDLE WINAPI fake_file(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa,
                               DWORD disposition, DWORD flags, HANDLE template_handle) {
    unsigned int i = current->request->index;
    if (i > 2 || !name || wcscmp(name, L"NUL") || !sa || !sa->bInheritHandle ||
        access != (i == 0 ? GENERIC_READ : GENERIC_WRITE) || share != 3 ||
        disposition != OPEN_EXISTING || flags != FILE_ATTRIBUTE_NORMAL || template_handle) {
        (void)bad(); return INVALID_HANDLE_VALUE;
    }
    return synthetic(i + 1u);
}
static BOOL WINAPI fake_info(HANDLE h, LPDWORD flags) {
    unsigned int i;
    if (!flags) return bad();
    for (i = 0; i < OF_HANDLE_COUNT; ++i) if (h == synthetic(i)) {
        *flags = i >= 1 && i <= 3 ? HANDLE_FLAG_INHERIT : 0; return TRUE;
    }
    return bad();
}
static BOOL WINAPI fake_attr_init(LPPROC_THREAD_ATTRIBUTE_LIST list, DWORD count, DWORD flags, PSIZE_T size) {
    if (count != 2 || flags || !size) return bad();
    if (!list) { *size = 128; current->error = ERROR_INSUFFICIENT_BUFFER; return FALSE; }
    if ((void *)list != (void *)current->slot->arena || *size != 128) return bad();
    return TRUE;
}
static BOOL WINAPI fake_attr_update(LPPROC_THREAD_ATTRIBUTE_LIST list, DWORD flags, DWORD_PTR key,
                                    PVOID values, SIZE_T bytes, PVOID previous, PSIZE_T returned) {
    OF_SLOT *s = current->slot; unsigned int i;
    if ((void *)list != (void *)s->arena || flags || previous || returned) return bad();
    if (key == PROC_THREAD_ATTRIBUTE_JOB_LIST) {
        if (values != s->job_values || bytes != sizeof(s->job_values) || s->job_values[0] != synthetic(0)) return bad();
    } else if (key == PROC_THREAD_ATTRIBUTE_HANDLE_LIST) {
        if (values != s->standard_values || bytes != sizeof(s->standard_values)) return bad();
        for (i = 0; i < 3; ++i) if (s->standard_values[i] != synthetic(i+1u)) return bad();
    } else return bad();
    return TRUE;
}
static VOID WINAPI fake_attr_delete(LPPROC_THREAD_ATTRIBUTE_LIST list) {
    /* Only accepted core calls this, with its own pinned arena. */
    if ((void *)list != (void *)current->slot->arena) (void)bad();
}
static BOOL WINAPI fake_process(LPCWSTR app, LPWSTR command, LPSECURITY_ATTRIBUTES psa,
    LPSECURITY_ATTRIBUTES tsa, BOOL inherit, DWORD flags, LPVOID environment,
    LPCWSTR directory, LPSTARTUPINFOW startup, LPPROCESS_INFORMATION out) {
    OF_SLOT *s = current->slot; STARTUPINFOEXW *ex = (STARTUPINFOEXW *)startup;
    if (app != s->launch.interpreter || command != s->command || psa || tsa || !inherit ||
        flags != OF_CREATION_FLAGS || environment != s->environment || directory != s->launch.directory ||
        !startup || startup->cb != sizeof(*ex) || (void *)ex->lpAttributeList != (void *)s->arena ||
        startup->dwFlags != STARTF_USESTDHANDLES || startup->hStdInput != synthetic(1) ||
        startup->hStdOutput != synthetic(2) || startup->hStdError != synthetic(3) || out != &s->process_info) return bad();
    out->hProcess = synthetic(4); out->hThread = synthetic(5);
    out->dwProcessId = 0; out->dwThreadId = 0; return TRUE;
}
static BOOL WINAPI fake_member(HANDLE process, HANDLE job, PBOOL yes) {
    if (process != synthetic(4) || job != synthetic(0) || !yes) return bad();
    *yes = TRUE; return TRUE;
}
static DWORD WINAPI fake_resume(HANDLE h) { if (h != synthetic(5)) { (void)bad(); return MAXDWORD; } return 1; }
static BOOL WINAPI fake_terminate(HANDLE h, UINT code) { return h == synthetic(0) && code == 0xD1A6u ? TRUE : bad(); }
static DWORD WINAPI fake_wait(HANDLE h, DWORD ms) {
    if (h != synthetic(4) || ms) { (void)bad(); return WAIT_FAILED; } return WAIT_OBJECT_0;
}
static BOOL WINAPI fake_exit(HANDLE h, LPDWORD code) {
    if (h != synthetic(4) || !code) return bad(); *code = 17; return TRUE;
}
static BOOL WINAPI fake_close(HANDLE h) {
    unsigned int i; for (i = 0; i < OF_HANDLE_COUNT; ++i) if (h == synthetic(i)) return TRUE;
    return bad();
}
static const OF_API fake_api = {
    fake_job, fake_limits, fake_query, fake_file, fake_info, fake_attr_init,
    fake_attr_update, fake_attr_delete, fake_process, fake_member, fake_resume,
    fake_terminate, fake_wait, fake_exit, fake_close, fake_error_get, fake_error_set
};

int32_t __cdecl of_inert_init_v1(OF_SLOT *s, uint64_t capacity, const OF_ID *id) {
    INERT_CONTEXT ctx = {s, NULL, 0}; int code;
    if (capacity != OF_SLOT_CAPACITY || capacity > (uint64_t)SIZE_MAX || !base(s, id)) return OF_INVALID;
    if (!enter(&ctx)) return OF_BUSY;
    code = of_slot_init(s, (size_t)capacity, id, &fake_api); leave(); return (int32_t)code;
}
int32_t __cdecl of_inert_apply_v1(OF_SLOT *s, const OF_ID *id, const OF_REQUEST *q, OF_RESULT *out) {
    INERT_CONTEXT ctx = {s, q, 0}; int code;
    if (!base(s, id) || !span(q, sizeof(*q), 8u) || !span(out, sizeof(*out), 8u) ||
        !separate(s, OF_SLOT_CAPACITY, q, sizeof(*q)) || !separate(s, OF_SLOT_CAPACITY, out, sizeof(*out)) ||
        !separate(id, sizeof(*id), q, sizeof(*q)) || !separate(id, sizeof(*id), out, sizeof(*out)) ||
        !separate(q, sizeof(*q), out, sizeof(*out))) return OF_INVALID;
    if (q->launch && (!span(q->launch, sizeof(*q->launch), 4u) ||
        !separate(q->launch, sizeof(*q->launch), s, OF_SLOT_CAPACITY) ||
        !separate(q->launch, sizeof(*q->launch), id, sizeof(*id)) ||
        !separate(q->launch, sizeof(*q->launch), q, sizeof(*q)) ||
        !separate(q->launch, sizeof(*q->launch), out, sizeof(*out)))) return OF_INVALID;
    if (q->launch && (!utf16_field(q->launch->interpreter) || !utf16_field(q->launch->script) ||
        !utf16_field(q->launch->directory) || !utf16_field(q->launch->system_root))) return OF_INVALID;
    if (!enter(&ctx)) return OF_BUSY;
    code = of_slot_apply(s, id, q, out); leave(); return (int32_t)code;
}
int32_t __cdecl of_inert_snapshot_v1(OF_SLOT *s, const OF_ID *id, OF_SNAPSHOT *out) {
    INERT_CONTEXT ctx = {s, NULL, 0}; int code;
    if (!base(s, id) || !span(out, sizeof(*out), 8u) ||
        !separate(s, OF_SLOT_CAPACITY, out, sizeof(*out)) || !separate(id, sizeof(*id), out, sizeof(*out))) return OF_INVALID;
    if (!enter(&ctx)) return OF_BUSY;
    code = of_slot_snapshot(s, id, out); leave(); return (int32_t)code;
}
