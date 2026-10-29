/* SOURCE ONLY until an explicit compile/inert-harness release. No OS API table. */
#include "owned_slot.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* Always active, including Release /DNDEBUG; intentionally not assert(). */
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "check failed line %d\n", __LINE__); abort(); } } while (0)
static OF_SLOT slot;
static OF_ID identity;
static OF_API api;
static DWORD error_value;
static uintptr_t handle_next;
static unsigned int native_calls, close_calls, create_calls, update_calls, delete_calls;
static unsigned int query_active, wait_status, process_mode, close_fail, init_fail, update_fail, reenter;
static HANDLE first_values[3];
static PVOID first_array;
static SIZE_T first_array_size;
static unsigned int first_array_set;

static HANDLE new_handle(void) { return (HANDLE)++handle_next; }
static DWORD WINAPI err_get(void) { return error_value; }
static void WINAPI err_set(DWORD value) { error_value = value; }
static HANDLE WINAPI job(LPSECURITY_ATTRIBUTES sa, LPCWSTR name) {
    OF_SNAPSHOT before; OF_RESULT result; OF_REQUEST request;
    ++native_calls; CHECK(!sa && !name);
    if (reenter) {
        memset(&before, 0xA5, sizeof(before));
        CHECK(of_slot_snapshot(&slot, &identity, &before) == OF_BUSY);
        CHECK(((unsigned char *)&before)[0] == 0xA5); /* busy never touches output */
        memset(&request, 0, sizeof(request)); request.sequence = 2; request.action = OF_ACTIVE;
        CHECK(of_slot_apply(&slot, &identity, &request, &result) == OF_BUSY);
        CHECK(of_slot_init(&slot, sizeof(slot), &identity, &api) == OF_BUSY);
    }
    return new_handle();
}
static BOOL WINAPI limit_set(HANDLE h, JOBOBJECTINFOCLASS kind, LPVOID data, DWORD size) {
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION *p = data;
    ++native_calls; CHECK(h && kind == JobObjectExtendedLimitInformation && size == sizeof(*p));
    CHECK(p->BasicLimitInformation.LimitFlags == OF_KILL_ON_CLOSE); return TRUE;
}
static BOOL WINAPI query(HANDLE h, JOBOBJECTINFOCLASS kind, LPVOID data, DWORD size, LPDWORD used) {
    ++native_calls; CHECK(h); *used = size;
    if (kind == JobObjectExtendedLimitInformation) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION *p = data;
        CHECK(size == sizeof(*p)); p->BasicLimitInformation.LimitFlags = OF_KILL_ON_CLOSE;
    } else {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION *p = data;
        CHECK(kind == JobObjectBasicAccountingInformation && size == sizeof(*p));
        p->ActiveProcesses = query_active;
    }
    return TRUE;
}
static HANDLE WINAPI file(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa,
                          DWORD disposition, DWORD flags, HANDLE template_handle) {
    ++native_calls; CHECK(wcscmp(name, L"NUL") == 0);
    CHECK(access == GENERIC_READ || access == GENERIC_WRITE);
    CHECK(share == 3 && sa->bInheritHandle && disposition == OPEN_EXISTING &&
          flags == FILE_ATTRIBUTE_NORMAL && !template_handle);
    return new_handle();
}
static BOOL WINAPI info(HANDLE h, LPDWORD flags) {
    ++native_calls; CHECK(h);
    *flags = ((uintptr_t)h >= 102 && (uintptr_t)h <= 104) ? HANDLE_FLAG_INHERIT : 0;
    return TRUE;
}
static BOOL WINAPI attr_init(LPPROC_THREAD_ATTRIBUTE_LIST p, DWORD count, DWORD flags, PSIZE_T size) {
    ++native_calls; CHECK(count == 2 && !flags);
    if (!p) { *size = init_fail == 2 ? OF_ARENA_CAPACITY + 1u : 128u; error_value = ERROR_INSUFFICIENT_BUFFER; return FALSE; }
    CHECK(*size >= 128);
    if (init_fail) { error_value = ERROR_INVALID_PARAMETER; return FALSE; }
    return TRUE;
}
static BOOL WINAPI update(LPPROC_THREAD_ATTRIBUTE_LIST list, DWORD flags, DWORD_PTR key,
                          PVOID values, SIZE_T size, PVOID previous, PSIZE_T returned) {
    ++native_calls; ++update_calls;
    CHECK(list && !flags && !previous && !returned);
    CHECK(key == PROC_THREAD_ATTRIBUTE_JOB_LIST || key == PROC_THREAD_ATTRIBUTE_HANDLE_LIST);
    if (!first_array_set) {
        first_array_set = 1; first_array = values; first_array_size = size;
        CHECK(size <= sizeof(first_values)); memcpy(first_values, values, size);
    }
    if (update_fail) { error_value = ERROR_INVALID_PARAMETER; return FALSE; }
    return TRUE;
}
static void WINAPI attr_delete(LPPROC_THREAD_ATTRIBUTE_LIST list) {
    ++native_calls; ++delete_calls; CHECK(list);
    if (first_array_set) CHECK(memcmp(first_array, first_values, first_array_size) == 0);
}
static BOOL WINAPI process(LPCWSTR app, LPWSTR command, LPSECURITY_ATTRIBUTES psa,
    LPSECURITY_ATTRIBUTES tsa, BOOL inherit, DWORD flags, LPVOID environment,
    LPCWSTR directory, LPSTARTUPINFOW startup, LPPROCESS_INFORMATION out) {
    STARTUPINFOEXW *extended = (STARTUPINFOEXW *)startup;
    ++native_calls; ++create_calls;
    CHECK(wcscmp(app, L"C:\\approved\\python.exe") == 0 && command && environment && directory);
    CHECK(!psa && !tsa && inherit && flags == OF_CREATION_FLAGS);
    CHECK(startup->cb == sizeof(*extended) && extended->lpAttributeList);
    CHECK(startup->hStdInput && startup->hStdOutput && startup->hStdError);
    CHECK(wcsstr(command, L" -I -S -B ") != NULL);
    out->hProcess = new_handle();
    if (process_mode != 1) out->hThread = new_handle();
    if (process_mode) { error_value = ERROR_ACCESS_DENIED; return FALSE; }
    return TRUE;
}
static BOOL WINAPI member(HANDLE process_handle, HANDLE job_handle, PBOOL yes) {
    ++native_calls; CHECK(process_handle && job_handle); *yes = TRUE; return TRUE;
}
static DWORD WINAPI resume(HANDLE h) { ++native_calls; CHECK(h); return 1; }
static BOOL WINAPI terminate(HANDLE h, UINT code) { ++native_calls; CHECK(h && code == 0xD1A6u); return TRUE; }
static DWORD WINAPI wait_for(HANDLE h, DWORD time) { ++native_calls; CHECK(h && !time); return wait_status; }
static BOOL WINAPI exit_code(HANDLE h, LPDWORD code) { ++native_calls; CHECK(h); *code = 17; return TRUE; }
static BOOL WINAPI close_handle(HANDLE h) {
    ++native_calls; ++close_calls; CHECK(h);
    if (close_fail) { error_value = ERROR_ACCESS_DENIED; return FALSE; }
    return TRUE;
}
static void setup(void) {
    memset(&slot, 0, sizeof(slot)); memset(&identity, 0, sizeof(identity));
    identity.operation[0] = 1; identity.generation[0] = 2; identity.role = 1;
    memset(&api, 0, sizeof(api));
    api.job = job; api.limits_set = limit_set; api.query = query; api.file = file;
    api.handle_info = info; api.attr_init = attr_init; api.attr_update = update;
    api.attr_delete = attr_delete; api.process = process; api.member = member;
    api.resume = resume; api.terminate = terminate; api.wait = wait_for;
    api.exit_code = exit_code; api.close = close_handle; api.error_get = err_get; api.error_set = err_set;
    error_value = 0; handle_next = 100; native_calls = close_calls = create_calls = update_calls = delete_calls = 0;
    query_active = wait_status = process_mode = close_fail = init_fail = update_fail = reenter = 0;
    first_array = NULL; first_array_set = 0; first_array_size = 0;
    CHECK(of_slot_init(&slot, sizeof(slot), &identity, &api) == OF_OK);
}
static OF_RESULT act(uint32_t kind, uint32_t index, uint64_t parameter, const OF_LAUNCH *launch) {
    OF_REQUEST request; OF_RESULT result; unsigned int before; int code;
    memset(&request, 0, sizeof(request)); memset(&result, 0, sizeof(result));
    request.sequence = slot.next_sequence; request.action = kind;
    request.index = index; request.parameter = parameter; request.launch = launch;
    before = slot.record_count;
    code = of_slot_apply(&slot, &identity, &request, &result);
    if (slot.record_count == before) { CHECK(code == OF_INVALID || code == OF_FULL || code == OF_STALE); result.code = (uint32_t)code; }
    else CHECK(code == (int)result.code);
    return result;
}
static void prepare_attributes(void) {
    unsigned int i;
    CHECK(act(OF_JOB, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_LIMIT_SET, 0, OF_KILL_ON_CLOSE, NULL).code == OF_OK);
    CHECK(act(OF_LIMIT_GET, 0, 0, NULL).code == OF_OK);
    for (i = 0; i < 3; ++i) CHECK(act(OF_STANDARD, i, 0, NULL).code == OF_OK);
    CHECK(act(OF_ATTR_INIT, 0, 0, NULL).code == OF_OK);
}
static void prepare(void) {
    prepare_attributes();
    CHECK(act(OF_ATTR_UPDATE, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_ATTR_UPDATE, 1, 0, NULL).code == OF_OK);
}
static OF_LAUNCH launch_input(void) {
    OF_LAUNCH p; memset(&p, 0, sizeof(p));
    wcscpy_s(p.interpreter, 512, L"C:\\approved\\python.exe");
    wcscpy_s(p.script, 512, L"C:\\approved\\windows_process_dummy.py");
    wcscpy_s(p.directory, 512, L"C:\\approved"); p.target = OF_DUMMY_WAIT; return p;
}

static void test_lost_return_replay_and_identity(void) {
    OF_REQUEST q; OF_RESULT r; OF_SNAPSHOT view; OF_ID changed; unsigned int calls;
    setup(); memset(&q, 0, sizeof(q)); q.sequence = 1; q.action = OF_JOB;
    (void)of_slot_apply(&slot, &identity, &q, &r); /* deliberately ignore status */
    CHECK(of_slot_snapshot(&slot, &identity, &view) == OF_OK);
    CHECK(view.life[0] == OF_OPEN && view.handles[0] == 101 && view.record_count == 1);
    calls = native_calls;
    CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_OK && r.replay == 1);
    CHECK(native_calls == calls);
    q.action = OF_CLOSE; CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_INVALID);
    q.action = OF_JOB; q.index = 1; CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_INVALID);
    q.index = 0; q.parameter = 1; CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_INVALID);
    changed = identity; changed.generation[0] = 3;
    CHECK(of_slot_init(&slot, sizeof(slot), &changed, &api) == OF_INVALID);
    CHECK(of_slot_init(&slot, sizeof(slot), &identity, &api) == OF_OK);
    CHECK(slot.record_count == 1 && slot.handles[0] == (HANDLE)(uintptr_t)101 && native_calls == calls);
}
static void test_capacity_alignment_stale(void) {
    static __declspec(align(8)) unsigned char buffer[OF_SLOT_CAPACITY + 8];
    OF_REQUEST q; OF_RESULT r; unsigned int i, calls;
    setup(); memset(buffer, 0, sizeof(buffer));
    CHECK(of_slot_init((OF_SLOT *)buffer, sizeof(OF_SLOT)-1, &identity, &api) == OF_INVALID);
    CHECK(of_slot_init((OF_SLOT *)(buffer+1), sizeof(OF_SLOT), &identity, &api) == OF_INVALID);
    buffer[sizeof(LONG)+1] = 1;
    CHECK(of_slot_init((OF_SLOT *)buffer, sizeof(OF_SLOT), &identity, &api) == OF_INVALID);
    CHECK(act(OF_JOB, 0, 0, NULL).code == OF_OK);
    for (i = 1; i < OF_NORMAL_RECORDS; ++i) CHECK(act(OF_LIMIT_GET, 0, 0, NULL).code == OF_OK);
    memset(&q, 0, sizeof(q)); q.sequence = slot.next_sequence; q.action = OF_LIMIT_GET;
    calls = native_calls;
    CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_FULL);
    q.sequence = UINT64_MAX; CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_INVALID);
    q.sequence = 0; CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_INVALID);
    q.sequence = slot.next_sequence + 1; CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_STALE);
    CHECK(native_calls == calls && slot.record_count == OF_NORMAL_RECORDS);
    q.sequence = 1; q.action = OF_JOB;
    CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_OK && r.replay);
    CHECK(act(OF_ACTIVE, 0, 0, NULL).code == OF_OK); /* final empty-job observation reserved */
    CHECK(act(OF_CLOSE, 0, 0, NULL).code == OF_OK && close_calls == 1);
}
static void test_reentrant_snapshot(void) {
    OF_SNAPSHOT view;
    setup(); reenter = 1;
    CHECK(act(OF_JOB, 0, 0, NULL).code == OF_OK);
    CHECK(of_slot_snapshot(&slot, &identity, &view) == OF_OK && view.record_count == 1);
}
static void test_partial_process_and_parameter_replay(void) {
    OF_LAUNCH p; OF_REQUEST q; OF_RESULT r; OF_SNAPSHOT view; unsigned int mode, calls;
    for (mode = 0; mode < 3; ++mode) {
        setup(); prepare(); p = launch_input(); process_mode = mode;
        memset(&q, 0, sizeof(q)); q.sequence = slot.next_sequence; q.action = OF_PROCESS;
        q.parameter = OF_CREATION_FLAGS; q.launch = &p;
        (void)of_slot_apply(&slot, &identity, &q, &r);
        CHECK(of_slot_snapshot(&slot, &identity, &view) == OF_OK && view.process_possible);
        CHECK(view.life[4] == OF_OPEN && (mode != 1 ? view.life[5] == OF_OPEN : view.life[5] == OF_ABSENT));
        calls = native_calls;
        CHECK(of_slot_apply(&slot, &identity, &q, &r) == (mode ? OF_FAILED : OF_OK));
        CHECK(r.replay && native_calls == calls);
        p.target = OF_DUMMY_TREE;
        CHECK(of_slot_apply(&slot, &identity, &q, &r) == OF_INVALID && native_calls == calls);
        CHECK(view.uncertain == (mode ? 1u : 0u));
    }
}
static void test_attribute_retention_and_failed_initialization(void) {
    OF_RESULT r; PVOID values; unsigned int count;
    setup(); prepare(); values = first_array; count = update_calls;
    r = act(OF_ATTR_UPDATE, 0, 0, NULL);
    CHECK(r.code == OF_INVALID && first_array == values && update_calls == count);
    CHECK(memcmp(first_array, first_values, first_array_size) == 0);
    CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_OK && delete_calls == 1);
    CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_INVALID && delete_calls == 1);
    setup(); prepare_attributes(); update_fail = 1;
    CHECK(act(OF_ATTR_UPDATE, 0, 0, NULL).code == OF_FAILED);
    values = first_array; count = update_calls;
    CHECK(act(OF_ATTR_UPDATE, 0, 0, NULL).code == OF_INVALID && update_calls == count);
    CHECK(first_array == values && memcmp(first_array, first_values, first_array_size) == 0);
    CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_OK);
    setup(); init_fail = 1;
    CHECK(act(OF_ATTR_INIT, 0, 0, NULL).code == OF_FAILED);
    CHECK(slot.attr_life == OF_ATTR_INIT_FAILED);
    CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_INVALID && delete_calls == 0);
    setup(); init_fail = 2;
    CHECK(act(OF_ATTR_INIT, 0, 0, NULL).code == OF_FAILED && slot.attr_life == OF_ATTR_INIT_FAILED);
    CHECK(native_calls == 1); /* no oversized initialization */
}
static void test_cleanup_and_no_unchanged_close_retry(void) {
    OF_LAUNCH p; OF_SNAPSHOT view; OF_REQUEST replay; OF_RESULT r; unsigned int before;
    setup(); prepare(); p = launch_input();
    CHECK(act(OF_PROCESS, 0, OF_CREATION_FLAGS, &p).code == OF_OK);
    CHECK(act(OF_MEMBER, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_RESUME, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_TERMINATE, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_WAIT, 0, 0, NULL).code == OF_OK);
    query_active = 1;
    CHECK(act(OF_ACTIVE, 0, 0, NULL).value == 1);
    CHECK(act(OF_CLOSE, 4, 0, NULL).code == OF_INVALID && close_calls == 0);
    query_active = 0; CHECK(act(OF_ACTIVE, 0, 0, NULL).value == 0);
    memset(&replay, 0, sizeof(replay)); replay.sequence = slot.next_sequence;
    replay.action = OF_CLOSE; replay.index = 5; close_fail = 1;
    CHECK(of_slot_apply(&slot, &identity, &replay, &r) == OF_FAILED);
    before = close_calls; close_fail = 0;
    CHECK(of_slot_apply(&slot, &identity, &replay, &r) == OF_FAILED && r.replay && close_calls == before);
    CHECK(act(OF_CLOSE, 5, 0, NULL).code == OF_INVALID && close_calls == before);
    CHECK(act(OF_CLOSE, 4, 0, NULL).code == OF_OK); /* independent disposal still allowed */
    CHECK(of_slot_snapshot(&slot, &identity, &view) == OF_OK);
    CHECK(view.uncertain && view.life[5] == OF_CLOSE_FAILED && view.life[4] == OF_CLOSED);
}

static void test_normal_exhaustion_cannot_starve_process_cleanup(void) {
    OF_LAUNCH p; OF_SNAPSHOT view; OF_REQUEST close_request; OF_RESULT result;
    unsigned int failure, i, calls;
    for (failure = 0; failure < 2; ++failure) {
        setup(); prepare(); p = launch_input();
        while (slot.normal_count < OF_NORMAL_RECORDS - 1u)
            CHECK(act(OF_LIMIT_GET, 0, 0, NULL).code == OF_OK);
        /* Last ordinary record can acquire process+thread, but cannot consume reserve. */
        CHECK(act(OF_PROCESS, 0, OF_CREATION_FLAGS, &p).code == OF_OK);
        CHECK(slot.normal_count == OF_NORMAL_RECORDS && slot.cleanup_count == 0);
        calls = native_calls;
        CHECK(act(OF_LIMIT_GET, 0, 0, NULL).code == OF_FULL);
        CHECK(act(OF_WAIT, 0, 0, NULL).code == OF_FULL); /* cannot burn final observations before termination */
        CHECK(native_calls == calls);
        CHECK(act(OF_TERMINATE, 0, 0, NULL).code == OF_OK);
        CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_OK);
        CHECK(act(OF_WAIT, 0, 0, NULL).code == OF_OK);
        CHECK(act(OF_ACTIVE, 0, 0, NULL).code == OF_OK);
        CHECK(act(OF_EXIT, 0, 0, NULL).code == OF_OK);
        memset(&close_request, 0, sizeof(close_request));
        close_request.sequence = slot.next_sequence; close_request.action = OF_CLOSE; close_request.index = 5;
        close_fail = failure;
        CHECK(of_slot_apply(&slot, &identity, &close_request, &result) == (failure ? OF_FAILED : OF_OK));
        calls = close_calls; close_fail = 0;
        CHECK(of_slot_apply(&slot, &identity, &close_request, &result) == (failure ? OF_FAILED : OF_OK));
        CHECK(result.replay && close_calls == calls);
        CHECK(act(OF_CLOSE, 5, 0, NULL).code == OF_INVALID && close_calls == calls);
        /* All remaining independent resource closes retain dedicated admission. */
        for (i = 1; i <= 4; ++i) CHECK(act(OF_CLOSE, i, 0, NULL).code == OF_OK);
        CHECK(act(OF_CLOSE, 0, 0, NULL).code == OF_OK);
        CHECK(close_calls == OF_HANDLE_COUNT);
        CHECK(of_slot_snapshot(&slot, &identity, &view) == OF_OK);
        CHECK(view.normal_count == OF_NORMAL_RECORDS && view.cleanup_count == 11);
        for (i = 0; i < OF_HANDLE_COUNT; ++i)
            CHECK(view.life[i] == (uint32_t)((failure && i == 5) ? OF_CLOSE_FAILED : OF_CLOSED));
        CHECK(view.uncertain == failure);
    }
}

static void test_bounded_final_polling_does_not_consume_close_credits(void) {
    OF_LAUNCH p; unsigned int i, before;
    setup(); prepare(); p = launch_input();
    CHECK(act(OF_PROCESS, 0, OF_CREATION_FLAGS, &p).code == OF_OK);
    CHECK(act(OF_TERMINATE, 0, 0, NULL).code == OF_OK);
    wait_status = WAIT_TIMEOUT;
    for (i = 0; i < 7; ++i) CHECK(act(OF_WAIT, 0, 0, NULL).code == OF_OK);
    wait_status = WAIT_OBJECT_0;
    CHECK(act(OF_WAIT, 0, 0, NULL).code == OF_OK);
    before = native_calls; CHECK(act(OF_WAIT, 0, 0, NULL).code == OF_FULL && native_calls == before);
    query_active = 1;
    for (i = 0; i < 7; ++i) CHECK(act(OF_ACTIVE, 0, 0, NULL).value == 1);
    query_active = 0;
    CHECK(act(OF_ACTIVE, 0, 0, NULL).code == OF_OK);
    before = native_calls; CHECK(act(OF_ACTIVE, 0, 0, NULL).code == OF_FULL && native_calls == before);
    CHECK(act(OF_EXIT, 0, 0, NULL).code == OF_OK);
    CHECK(act(OF_ATTR_DELETE, 0, 0, NULL).code == OF_OK);
    for (i = 1; i < OF_HANDLE_COUNT; ++i) CHECK(act(OF_CLOSE, i, 0, NULL).code == OF_OK);
    CHECK(act(OF_CLOSE, 0, 0, NULL).code == OF_OK);
    CHECK(slot.cleanup_count == 25 && close_calls == OF_HANDLE_COUNT);
}

int main(void) {
    test_lost_return_replay_and_identity();
    test_capacity_alignment_stale();
    test_reentrant_snapshot();
    test_partial_process_and_parameter_replay();
    test_attribute_retention_and_failed_initialization();
    test_cleanup_and_no_unchanged_close_retry();
    test_normal_exhaustion_cannot_starve_process_cleanup();
    test_bounded_final_polling_does_not_consume_close_credits();
    puts("owned_slot inert scenarios passed (C fake table only)");
    return 0;
}
