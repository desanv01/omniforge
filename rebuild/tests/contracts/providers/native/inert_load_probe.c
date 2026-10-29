/* SOURCE ONLY. Native single-thread disposable probe, NOT a Python loader.
 * Immutable artifact custody/dependency review and parent ownership precede launch.
 * Never link the target implementation/import library into this executable. */
#include "slot_inert_exports.h"
#include <stdio.h>
#include <string.h>
#include <wchar.h>

typedef int32_t (__cdecl *DESCRIPTOR_FN)(void *, uint32_t);
typedef int32_t (__cdecl *INIT_FN)(OF_SLOT *, uint64_t, const OF_ID *);
typedef int32_t (__cdecl *APPLY_FN)(OF_SLOT *, const OF_ID *, const OF_REQUEST *, OF_RESULT *);
typedef int32_t (__cdecl *SNAPSHOT_FN)(OF_SLOT *, const OF_ID *, OF_SNAPSHOT *);
typedef union PROBE_SLOT { uint64_t alignment; unsigned char bytes[131072]; } PROBE_SLOT;
enum STAGE {
    PROBE_INPUT = 1, PROBE_LOAD, PROBE_PIN, PROBE_SYMBOLS, PROBE_DESCRIPTOR, PROBE_INIT,
    PROBE_JOB, PROBE_REPLAY, PROBE_ACTIVE, PROBE_CLOSE, PROBE_SNAPSHOT, PROBE_DONE
};
static struct {
    enum STAGE stage;
    DWORD error;
    int32_t call_code;
    HMODULE initial, pins[4];
    FARPROC raw[4];
    DESCRIPTOR_FN descriptor;
    INIT_FN init;
    APPLY_FN apply;
    SNAPSHOT_FN snapshot;
    uint64_t descriptor_storage[71];
    int descriptor_read;
    PROBE_SLOT storage;
    OF_ID id;
    OF_REQUEST request;
    OF_RESULT result, original;
    OF_SNAPSHOT view;
    uint64_t job_value;
    char operation[33], generation[33], receipt[65];
} probe;

/* Independent literal fixture. Do not generate from OF_INERT_FIELDS/sizeof or
 * from loaded output. Header plus136 values,142 LE u32 words/568bytes. */
static const uint32_t expected[142] = {
    0x4942464Fu, 1, 568, 142, 6, 136,
    1, 0x8664, 1, 1, 8, 8, 8, 8, 8, 8, 4, 4, 1,
    4, 4, 1, 8, 8, 1, 2, 2, 1, 4, 4, 1, 4, 4, 1,
    131072, 86424, 8, 65536, 14744, 8, 64, 96, 64, 32, 11, 8, 8, 1,
    0x08080404, 0x2000, 16, 16, 1, 1, 512, 4, 6,
    36, 4, 0, 16, 32, 4100, 4, 0, 1024, 2048, 3072, 4096,
    32, 8, 0, 8, 12, 16, 24, 32, 8, 0, 4, 8, 16, 24,
    184, 8, 0, 40, 48, 52, 56, 60, 64, 112, 136, 140, 144, 148, 152,
    0, 1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    0, 1, 2, 3, 4, 5, 0, 1, 2, 3, 0, 1, 2, 3, 4, 5, 1, 2, 3, 1, 2, 3
};
static const char *const names[4] = {
    "of_inert_descriptor_v1", "of_inert_init_v1", "of_inert_apply_v1", "of_inert_snapshot_v1"
};
_Static_assert(sizeof(expected) == 568, "fixed independent descriptor fixture");
_Static_assert(sizeof(probe.descriptor_storage) == 568, "fixed descriptor output");
_Static_assert(sizeof(probe.storage) == 131072, "opaque slot capacity");
/* Exact reviewed MSVC-x64 function/address representations only. memcpy avoids
 * cast diagnostics/aliasing, does not claim portable C ABI interoperability. */
_Static_assert(sizeof(FARPROC) == sizeof(LPCWSTR), "Win32 FROM_ADDRESS representation");
_Static_assert(sizeof(FARPROC) == sizeof(DESCRIPTOR_FN), "descriptor binding width");
_Static_assert(sizeof(FARPROC) == sizeof(INIT_FN), "init binding width");
_Static_assert(sizeof(FARPROC) == sizeof(APPLY_FN), "apply binding width");
_Static_assert(sizeof(FARPROC) == sizeof(SNAPSHOT_FN), "snapshot binding width");

static int finish(int exit_code) {
    unsigned int i; const unsigned char *p = (const unsigned char *)probe.descriptor_storage;
    /* Fixed ASCII fields only. No path, raw pointer or uncontrolled error text. */
    if (printf("OF_INERT_LOAD_V1 operation=%s generation=%s receipt=%s stage=%u error=%lu code=%ld pass=%u descriptor=",
        probe.operation, probe.generation, probe.receipt, (unsigned int)probe.stage,
        (unsigned long)probe.error, (long)probe.call_code, exit_code == 0 ? 1u : 0u) < 0) return 9;
    if (probe.descriptor_read) {
        for (i = 0; i < 568; ++i) if (printf("%02x", (unsigned int)p[i]) < 0) return 9;
    } else if (putchar('-') == EOF) return 9;
    if (putchar('\n') == EOF || fflush(stdout) == EOF) return 9;
    return exit_code; /* pass text alone never sufficient; parent must observe exit0 */
}
static int hex(const WCHAR *s, size_t count, char *ascii, uint8_t *bytes) {
    size_t i; unsigned int accumulated = 0, high = 0;
    if (!s || wcsnlen_s(s, count+1u) != count) return 0;
    for (i = 0; i < count; ++i) {
        unsigned int v;
        if (s[i] >= L'0' && s[i] <= L'9') v = (unsigned int)(s[i]-L'0');
        else if (s[i] >= L'a' && s[i] <= L'f') v = (unsigned int)(s[i]-L'a')+10u;
        else return 0;
        ascii[i] = (char)s[i]; accumulated |= v;
        if (i % 2u == 0) high = v;
        else if (bytes) bytes[i/2u] = (uint8_t)((high << 4) | v);
    }
    ascii[count] = 0; return accumulated != 0;
}
static int reserved(const WCHAR *p, size_t n) {
    char base[5] = {0}; size_t i = 0;
    while (i < n && p[i] != L'.') {
        WCHAR c = p[i]; if (i >= 4) return 0;
        if (c >= L'a' && c <= L'z') c = (WCHAR)(c-L'a'+L'A');
        base[i++] = (char)c;
    }
    if (!strcmp(base, "CON") || !strcmp(base, "PRN") || !strcmp(base, "AUX") || !strcmp(base, "NUL")) return 1;
    return i == 4 && base[3] >= '1' && base[3] <= '9' &&
        ((!memcmp(base, "COM", 3)) || (!memcmp(base, "LPT", 3)));
}
static int artifact_path(const WCHAR *p) {
    size_t n, start, i;
    if (!p) return 0;
    n = wcsnlen_s(p, 1024);
    if (n < 4 || n >= 1024 || !((p[0] >= L'A' && p[0] <= L'Z') || (p[0] >= L'a' && p[0] <= L'z')) ||
        p[1] != L':' || p[2] != L'\\') return 0;
    start = 3;
    for (i = 3; i <= n; ++i) {
        WCHAR c = p[i];
        if (c == L'\\' || !c) {
            size_t length = i-start;
            if (!length || p[i-1u] == L'.' || p[i-1u] == L' ' ||
                (length == 1 && p[start] == L'.') ||
                (length == 2 && p[start] == L'.' && p[start+1u] == L'.') || reserved(p+start, length)) return 0;
            if (!c) return wcscmp(p+start, L"owned_slot_inert_exports.dll") == 0;
            start = i+1u;
        } else if (!((c >= L'A' && c <= L'Z') || (c >= L'a' && c <= L'z') ||
            (c >= L'0' && c <= L'9') || c == L'_' || c == L'-' || c == L'.' || c == L' ')) return 0;
    }
    return 0;
}
static int pin_symbol(unsigned int i) {
    LPCWSTR address;
    probe.raw[i] = GetProcAddress(probe.initial, names[i]);
    if (!probe.raw[i]) { probe.error = GetLastError(); return 0; }
    memcpy(&address, &probe.raw[i], sizeof(address));
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
        address, &probe.pins[i])) { probe.error = GetLastError(); return 0; }
    return probe.pins[i] == probe.initial; /* reject forwarded/foreign symbols */
}
static int read_snapshot(void) {
    probe.call_code = probe.snapshot((OF_SLOT *)probe.storage.bytes, &probe.id, &probe.view);
    return probe.call_code == OF_OK && !memcmp(probe.view.id.operation, probe.id.operation, 16) &&
        !memcmp(probe.view.id.generation, probe.id.generation, 16) && probe.view.id.role == probe.id.role &&
        probe.view.uncertain == 0;
}
static int apply(void) {
    probe.call_code = probe.apply((OF_SLOT *)probe.storage.bytes, &probe.id, &probe.request, &probe.result);
    return probe.call_code == OF_OK && probe.result.code == (uint32_t)OF_OK && probe.result.error == 0;
}
int wmain(int argc, WCHAR **argv) {
    unsigned int i; const unsigned char *wire = (const unsigned char *)probe.descriptor_storage;
    probe.stage = PROBE_INPUT;
    if (argc != 9 || wcscmp(argv[1], L"--artifact") || wcscmp(argv[3], L"--operation") ||
        wcscmp(argv[5], L"--generation") || wcscmp(argv[7], L"--receipt") || !artifact_path(argv[2]) ||
        !hex(argv[4], 32, probe.operation, probe.id.operation) ||
        !hex(argv[6], 32, probe.generation, probe.id.generation) || !hex(argv[8], 64, probe.receipt, NULL)) return finish(2);
    probe.id.role = 1;
    probe.stage = PROBE_LOAD;
    /* --receipt identifies OPERATOR-verified immutable custody, not an in-probe
     * hash verifier. No authority is inferred from its syntax or from path alone. */
    probe.initial = LoadLibraryExW(argv[2], NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!probe.initial) { probe.error = GetLastError(); return finish(3); }
    probe.stage = PROBE_PIN;
    if (!pin_symbol(0)) return finish(4);
    probe.stage = PROBE_SYMBOLS;
    for (i = 1; i < 4; ++i) if (!pin_symbol(i)) return finish(4);
    memcpy(&probe.descriptor, &probe.raw[0], sizeof(probe.descriptor));
    memcpy(&probe.init, &probe.raw[1], sizeof(probe.init));
    memcpy(&probe.apply, &probe.raw[2], sizeof(probe.apply));
    memcpy(&probe.snapshot, &probe.raw[3], sizeof(probe.snapshot));
    probe.stage = PROBE_DESCRIPTOR;
    probe.call_code = probe.descriptor(probe.descriptor_storage, UINT32_C(568));
    if (probe.call_code != OF_OK) return finish(5);
    probe.descriptor_read = 1;
    for (i = 0; i < 142; ++i) {
        uint32_t actual = (uint32_t)wire[4u*i] | ((uint32_t)wire[4u*i+1u] << 8) |
            ((uint32_t)wire[4u*i+2u] << 16) | ((uint32_t)wire[4u*i+3u] << 24);
        if (actual != expected[i]) return finish(5);
    }
    probe.stage = PROBE_INIT;
    probe.call_code = probe.init((OF_SLOT *)probe.storage.bytes, UINT64_C(131072), &probe.id);
    if (probe.call_code != OF_OK || !read_snapshot() || probe.view.next_sequence != 1 ||
        probe.view.record_count != 0 || probe.view.normal_count != 0 || probe.view.cleanup_count != 0) return finish(6);
    for (i = 0; i < 6; ++i) if (probe.view.life[i] != (uint32_t)OF_ABSENT || probe.view.handles[i] != 0) return finish(6);
    probe.stage = PROBE_JOB;
    probe.request.sequence = 1; probe.request.action = OF_JOB;
    if (!apply() || probe.result.replay != 0 || probe.result.raw == 0) return finish(7);
    probe.original = probe.result; probe.job_value = probe.result.raw;
    if (!read_snapshot() || probe.view.next_sequence != 2 || probe.view.record_count != 1 ||
        probe.view.normal_count != 1 || probe.view.cleanup_count != 0 ||
        probe.view.life[0] != (uint32_t)OF_OPEN || probe.view.handles[0] != probe.job_value) return finish(7);
    probe.stage = PROBE_REPLAY; /* exact SAME request and original input addresses */
    if (!apply() || probe.result.replay != 1 || probe.result.code != probe.original.code ||
        probe.result.error != probe.original.error || probe.result.raw != probe.original.raw ||
        probe.result.value != probe.original.value || !read_snapshot() || probe.view.next_sequence != 2 ||
        probe.view.record_count != 1 || probe.view.normal_count != 1 || probe.view.cleanup_count != 0) return finish(7);
    probe.stage = PROBE_ACTIVE;
    probe.request.sequence = 2; probe.request.action = OF_ACTIVE;
    if (!apply() || probe.result.replay != 0 || probe.result.value != 0 || !read_snapshot() ||
        probe.view.next_sequence != 3 || probe.view.record_count != 2 || probe.view.normal_count != 2 ||
        probe.view.cleanup_count != 0 || probe.view.zero_active_observed != 1) return finish(7);
    probe.stage = PROBE_CLOSE;
    probe.request.sequence = 3; probe.request.action = OF_CLOSE;
    if (!apply() || probe.result.replay != 0) return finish(7);
    probe.stage = PROBE_SNAPSHOT;
    if (!read_snapshot() || probe.view.next_sequence != 4 || probe.view.record_count != 3 ||
        probe.view.normal_count != 2 || probe.view.cleanup_count != 1 ||
        probe.view.life[0] != (uint32_t)OF_CLOSED || probe.view.handles[0] != probe.job_value ||
        probe.view.attr_life != (uint32_t)OF_ATTR_ABSENT || probe.view.process_possible != 0 ||
        probe.view.zero_active_observed != 1 || probe.view.last.code != (uint32_t)OF_OK || probe.view.last.replay != 0) return finish(7);
    for (i = 1; i < 6; ++i) if (probe.view.life[i] != (uint32_t)OF_ABSENT || probe.view.handles[i] != 0) return finish(7);
    probe.stage = PROBE_DONE;
    return finish(0); /* static HMODULE/pins retained until process termination */
}
