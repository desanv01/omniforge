#ifndef OF_OWNED_SLOT_H
#define OF_OWNED_SLOT_H
/* Windows-x64 source contract. No real symbol table, loader or Python callbacks. */
#if !defined(_WIN32) || !defined(_M_X64) || !defined(_MSC_VER)
#error Supported source target is MSVC Windows x64 only
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>

#define OF_SLOT_CAPACITY 131072u
#define OF_ARENA_CAPACITY 65536u
#define OF_RECORDS 96u
#define OF_NORMAL_RECORDS 64u
#define OF_CLEANUP_RECORDS 32u
#define OF_CLEANUP_BUCKETS 11u
#define OF_MAGIC UINT64_C(0x4f464f574e534c31)
#define OF_VERSION 1u
#define OF_CREATION_FLAGS 0x08080404u
#define OF_KILL_ON_CLOSE 0x2000u

enum OF_CODE { OF_OK, OF_FAILED, OF_INVALID, OF_BUSY, OF_STALE, OF_FULL, OF_UNKNOWN };
enum OF_ACTION {
    OF_JOB = 1, OF_LIMIT_SET, OF_LIMIT_GET, OF_STANDARD, OF_ATTR_INIT,
    OF_ATTR_UPDATE, OF_PROCESS, OF_MEMBER, OF_RESUME, OF_TERMINATE,
    OF_WAIT, OF_ACTIVE, OF_EXIT, OF_ATTR_DELETE, OF_CLOSE
};
enum OF_RESOURCE { OF_JOB_HANDLE, OF_STDIN_HANDLE, OF_STDOUT_HANDLE,
                   OF_STDERR_HANDLE, OF_PROCESS_HANDLE, OF_THREAD_HANDLE, OF_HANDLE_COUNT };
enum OF_LIFE { OF_ABSENT, OF_OPEN, OF_CLOSED, OF_CLOSE_FAILED };
enum OF_ATTR_LIFE { OF_ATTR_ABSENT, OF_ATTR_INITIALIZING, OF_ATTR_READY,
                    OF_ATTR_INIT_FAILED, OF_ATTR_DESTROYING, OF_ATTR_DESTROYED };
enum OF_TARGET { OF_DUMMY_WAIT = 1, OF_DUMMY_TREE, OF_DUMMY_SETTLEMENT };

typedef struct OF_ID {
    uint8_t operation[16];
    uint8_t generation[16]; /* opaque per-role UUID bytes, not invocation integer */
    uint32_t role;         /* child=1, authority=2, settlement=3 */
} OF_ID;

typedef struct OF_LAUNCH {
    WCHAR interpreter[512];
    WCHAR script[512];
    WCHAR directory[512];
    WCHAR system_root[512]; /* optional; only explicit environment entry */
    uint32_t target;
} OF_LAUNCH;

typedef struct OF_REQUEST {
    uint64_t sequence;
    uint32_t action;
    uint32_t index;
    uint64_t parameter; /* flags/zero timeout; fixed per action, never a handle */
    const OF_LAUNCH *launch; /* PROCESS only, pinned during call; copied into slot */
} OF_REQUEST;

typedef struct OF_RESULT {
    uint32_t code;
    uint32_t error;
    uint64_t raw;
    uint64_t value;
    uint32_t replay; /* history only: never a new action */
} OF_RESULT;

/* Native C functions only. The source/harness never fills this with Python or OS
 * bindings. The immutable exact table and pointed DLL must outlive all resources. */
typedef struct OF_API {
    HANDLE (WINAPI *job)(LPSECURITY_ATTRIBUTES, LPCWSTR);
    BOOL (WINAPI *limits_set)(HANDLE, JOBOBJECTINFOCLASS, LPVOID, DWORD);
    BOOL (WINAPI *query)(HANDLE, JOBOBJECTINFOCLASS, LPVOID, DWORD, LPDWORD);
    HANDLE (WINAPI *file)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
    BOOL (WINAPI *handle_info)(HANDLE, LPDWORD);
    BOOL (WINAPI *attr_init)(LPPROC_THREAD_ATTRIBUTE_LIST, DWORD, DWORD, PSIZE_T);
    BOOL (WINAPI *attr_update)(LPPROC_THREAD_ATTRIBUTE_LIST, DWORD, DWORD_PTR, PVOID, SIZE_T, PVOID, PSIZE_T);
    VOID (WINAPI *attr_delete)(LPPROC_THREAD_ATTRIBUTE_LIST);
    BOOL (WINAPI *process)(LPCWSTR, LPWSTR, LPSECURITY_ATTRIBUTES, LPSECURITY_ATTRIBUTES,
                          BOOL, DWORD, LPVOID, LPCWSTR, LPSTARTUPINFOW, LPPROCESS_INFORMATION);
    BOOL (WINAPI *member)(HANDLE, HANDLE, PBOOL);
    DWORD (WINAPI *resume)(HANDLE);
    BOOL (WINAPI *terminate)(HANDLE, UINT);
    DWORD (WINAPI *wait)(HANDLE, DWORD);
    BOOL (WINAPI *exit_code)(HANDLE, LPDWORD);
    BOOL (WINAPI *close)(HANDLE);
    DWORD (WINAPI *error_get)(void);
    VOID (WINAPI *error_set)(DWORD);
} OF_API;

typedef struct OF_RECORD {
    uint64_t sequence;
    uint64_t parameter;
    uint32_t action;
    uint32_t index;
    uint32_t finished;
    OF_RESULT result;
} OF_RECORD;

/* Caller allocates zeroed, >=8-aligned storage and strongly registers it BEFORE
 * init. Never free/reset/reuse/unload while resources or unknown actions remain.
 * Fields are public for ABI layout only: caller mutation after init unsupported. */
/* HANDLE/uint64_t provide natural x64 alignment; static assertions in the C
 * implementation keep the slot/arena alignment and capacity fail-closed. */
typedef struct OF_SLOT {
    volatile LONG guard; /* accessed only with interlocked operations */
    uint32_t version;
    uint64_t magic;
    OF_ID id;
    const OF_API *api;
    uint64_t next_sequence;
    uint32_t record_count;
    uint32_t normal_count;
    uint32_t cleanup_count;
    uint32_t cleanup_started;
    uint32_t cleanup_uses[OF_CLEANUP_BUCKETS];
    uint32_t uncertain;
    uint32_t blocked; /* no further work after any recorded non-success */
    HANDLE handles[OF_HANDLE_COUNT];
    uint32_t life[OF_HANDLE_COUNT];
    uint32_t acquire_attempt[OF_HANDLE_COUNT];
    uint32_t close_attempt[OF_HANDLE_COUNT];
    uint32_t limit_attempt;
    uint32_t limits_verified;
    uint32_t process_attempt;
    uint64_t launch_sequence;
    uint32_t process_possible;
    uint32_t member_verified;
    uint32_t resume_attempt;
    uint32_t terminate_attempt;
    uint32_t attr_life;
    uint32_t attr_attempt;
    uint32_t attr_update_attempt[2];
    uint32_t attr_delete_attempt;
    uint32_t root_signaled;
    uint32_t zero_active_observed;
    SIZE_T attr_size;
    HANDLE job_values[1];
    HANDLE standard_values[3];
    PROCESS_INFORMATION process_info;
    OF_LAUNCH launch;
    WCHAR command[4096];
    WCHAR environment[1024];
    uint32_t arena_alignment_padding; /* explicit former four-byte arena padding */
    unsigned char arena[OF_ARENA_CAPACITY];
    OF_RECORD records[OF_RECORDS];
} OF_SLOT;

typedef struct OF_SNAPSHOT {
    OF_ID id;
    uint64_t next_sequence;
    uint32_t record_count;
    uint32_t normal_count;
    uint32_t cleanup_count;
    uint32_t uncertain;
    uint64_t handles[OF_HANDLE_COUNT];
    uint32_t life[OF_HANDLE_COUNT];
    uint32_t attr_life;
    uint32_t process_possible;
    uint32_t root_signaled;
    uint32_t zero_active_observed;
    OF_RESULT last;
} OF_SNAPSHOT;

/* Nonblocking; BUSY performs no ledger/snapshot read or mutation. Finite sequence;
 * exact replay copies recorded result; mismatched/stale/full never calls API. */
int of_slot_init(OF_SLOT *, size_t capacity, const OF_ID *, const OF_API *);
int of_slot_apply(OF_SLOT *, const OF_ID *, const OF_REQUEST *, OF_RESULT *);
int of_slot_snapshot(OF_SLOT *, const OF_ID *, OF_SNAPSHOT *);

#endif
