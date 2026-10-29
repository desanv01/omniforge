/* SOURCE ONLY. Include wrapper TU to inspect private guard/context without any
 * additional public export, external API injection or changed accepted core. */
#include "slot_inert_exports.c"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "inert export check line %d\n", __LINE__); abort(); } } while (0)
typedef union STORAGE { uint64_t alignment; unsigned char bytes[OF_SLOT_CAPACITY]; } STORAGE;
static STORAGE first, second;
static OF_ID one = {{1}, {2}, 1}, two = {{3}, {4}, 2};
static OF_SLOT *a(void) { return (OF_SLOT *)first.bytes; }
static OF_SLOT *b(void) { return (OF_SLOT *)second.bytes; }
static OF_RESULT action(OF_SLOT *s, const OF_ID *id, uint32_t kind, uint32_t index, uint64_t parameter, const OF_LAUNCH *launch) {
    OF_REQUEST q = {0}; OF_RESULT r = {0}; int32_t code;
    q.sequence = s->next_sequence; q.action = kind; q.index = index; q.parameter = parameter; q.launch = launch;
    code = of_inert_apply_v1(s, id, &q, &r); CHECK(code == (int32_t)r.code); return r;
}
static uint32_t word(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static void descriptor_test(void) {
    uint32_t buffer[142]; unsigned char *p = (unsigned char *)buffer;
    memset(buffer, 0xA5, sizeof(buffer));
    _Static_assert(OF_D_COUNT == 136 && OF_INERT_BYTES == 568, "fixed descriptor count and bytes");
    CHECK(of_inert_descriptor_v1(buffer, 564) == OF_INVALID && p[0] == 0xA5);
    CHECK(of_inert_descriptor_v1(NULL, 568) == OF_INVALID);
    CHECK(of_inert_descriptor_v1(p+1, 568) == OF_INVALID && p[0] == 0xA5);
    CHECK(of_inert_descriptor_v1(buffer, sizeof(buffer)) == OF_OK);
    CHECK(word(p) == 0x4942464fu && word(p+4) == 1 && word(p+8) == 568 && word(p+12) == 142);
    CHECK(word(p+4u*(6u+OF_D_slot_size)) == 86424);
    CHECK(word(p+4u*(6u+OF_D_arena_offset)) == 14744);
    CHECK(word(p+4u*(6u+OF_D_request_launch)) == 24);
    CHECK(word(p+4u*(6u+OF_D_snapshot_last)) == 152);
    CHECK(word(p+4u*(6u+OF_D_wchar_size)) == 2);
}
static void refusal_and_guard_test(void) {
    OF_SNAPSHOT out; OF_RESULT r; OF_REQUEST q = {1, OF_JOB, 0, 0, NULL};
    INERT_CONTEXT ctx = {a(), &q, 0};
    memset(&out, 0xA5, sizeof(out)); memset(&r, 0xA5, sizeof(r));
    CHECK(of_inert_init_v1(a(), 1, &one) == OF_INVALID);
    CHECK(of_inert_init_v1((OF_SLOT *)(first.bytes+1), OF_SLOT_CAPACITY, &one) == OF_INVALID);
    CHECK(of_inert_init_v1(a(), OF_SLOT_CAPACITY, NULL) == OF_INVALID);
    CHECK(of_inert_init_v1(a(), OF_SLOT_CAPACITY, &one) == OF_OK);
    CHECK(of_inert_init_v1(b(), OF_SLOT_CAPACITY, &two) == OF_OK);
    CHECK(of_inert_snapshot_v1(a(), &two, &out) == OF_INVALID && ((unsigned char *)&out)[0] == 0xA5);
    CHECK(of_inert_apply_v1(a(), &one, &q, (OF_RESULT *)first.bytes) == OF_INVALID);
    CHECK(enter(&ctx));
    CHECK(of_inert_apply_v1(a(), &one, &q, &r) == OF_BUSY && ((unsigned char *)&r)[0] == 0xA5);
    CHECK(of_inert_snapshot_v1(b(), &two, &out) == OF_BUSY && ((unsigned char *)&out)[0] == 0xA5);
    CHECK(of_inert_init_v1(b(), OF_SLOT_CAPACITY, &two) == OF_BUSY && current == &ctx);
    leave(); CHECK(current == NULL && wrapper_guard == 0);
    (void)_InterlockedExchange(&a()->guard, 1);
    CHECK(of_inert_snapshot_v1(a(), &one, &out) == OF_BUSY && ((unsigned char *)&out)[0] == 0xA5);
    CHECK(current == NULL && wrapper_guard == 0);
    (void)_InterlockedExchange(&a()->guard, 0);
}
static void replay_and_invalid_test(void) {
    OF_RESULT r, replay; OF_SNAPSHOT snap; OF_REQUEST q = {0}; uint64_t next;
    CHECK(action(a(), &one, OF_JOB, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(b(), &two, OF_JOB, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(a()->handles[0] == b()->handles[0]); /* synthetic equality is NOT shared authority */
    CHECK(action(b(), &two, OF_LIMIT_SET, 0, OF_KILL_ON_CLOSE, NULL).code == (uint32_t)OF_OK);
    CHECK(a()->limit_attempt == 0 && a()->record_count == 1);
    q.sequence = b()->next_sequence; q.action = OF_LIMIT_SET; q.parameter = OF_KILL_ON_CLOSE;
    CHECK(of_inert_apply_v1(b(), &two, &q, &r) == OF_INVALID);
    CHECK(r.code == (uint32_t)OF_INVALID && r.replay == 0 && b()->record_count == 3);
    next = b()->next_sequence;
    CHECK(of_inert_apply_v1(b(), &two, &q, &replay) == OF_INVALID);
    CHECK(replay.code == r.code && replay.replay == 1 && b()->next_sequence == next && b()->limit_attempt == 1);
    CHECK(action(b(), &two, OF_ACTIVE, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(b(), &two, OF_CLOSE, 0, 0, NULL).code == (uint32_t)OF_OK);
    memset(&r, 0xA5, sizeof(r)); q.sequence = b()->next_sequence; q.action = OF_CLOSE; q.parameter = 0;
    next = b()->next_sequence;
    CHECK(of_inert_apply_v1(b(), &two, &q, &r) == OF_INVALID);
    CHECK(((unsigned char *)&r)[0] == 0xA5 && b()->next_sequence == next);
    CHECK(of_inert_snapshot_v1(b(), &two, &snap) == OF_OK);
    CHECK(snap.life[0] == (uint32_t)OF_CLOSED && snap.handles[0] != 0 && a()->life[0] == (uint32_t)OF_OPEN);
}
static void flow_test(void) {
    OF_LAUNCH launch = {0}; OF_SNAPSHOT snap; unsigned int i;
    OF_REQUEST q = {0}; OF_RESULT refused; uint64_t next;
    wcscpy_s(launch.interpreter, 512, L"C:\\approved\\python.exe");
    wcscpy_s(launch.script, 512, L"C:\\approved\\windows_process_dummy.py");
    wcscpy_s(launch.directory, 512, L"C:\\approved"); launch.target = OF_DUMMY_WAIT;
    q.sequence = a()->next_sequence; q.action = OF_PROCESS; q.parameter = OF_CREATION_FLAGS; q.launch = &launch;
    next = a()->next_sequence; memset(&refused, 0xA5, sizeof(refused));
    launch.system_root[0] = 0xD800u;
    CHECK(of_inert_apply_v1(a(), &one, &q, &refused) == OF_INVALID && a()->next_sequence == next);
    CHECK(((unsigned char *)&refused)[0] == 0xA5); launch.system_root[0] = 0;
    CHECK(action(a(), &one, OF_LIMIT_SET, 0, OF_KILL_ON_CLOSE, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_LIMIT_GET, 0, 0, NULL).code == (uint32_t)OF_OK);
    for (i = 0; i < 3; ++i) CHECK(action(a(), &one, OF_STANDARD, i, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_ATTR_INIT, 0, 0, NULL).code == (uint32_t)OF_OK);
    for (i = 0; i < 2; ++i) CHECK(action(a(), &one, OF_ATTR_UPDATE, i, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_PROCESS, 0, OF_CREATION_FLAGS, &launch).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_MEMBER, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_RESUME, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_TERMINATE, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_WAIT, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_ACTIVE, 0, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(action(a(), &one, OF_EXIT, 0, 0, NULL).value == 17);
    CHECK(action(a(), &one, OF_ATTR_DELETE, 0, 0, NULL).code == (uint32_t)OF_OK);
    for (i = 0; i < OF_HANDLE_COUNT; ++i) CHECK(action(a(), &one, OF_CLOSE, i, 0, NULL).code == (uint32_t)OF_OK);
    CHECK(of_inert_snapshot_v1(a(), &one, &snap) == OF_OK && snap.uncertain == 0);
    for (i = 0; i < OF_HANDLE_COUNT; ++i) CHECK(snap.life[i] == (uint32_t)OF_CLOSED && snap.handles[i] != 0);
    CHECK(snap.attr_life == (uint32_t)OF_ATTR_DESTROYED && snap.root_signaled && snap.zero_active_observed);
}
int main(void) {
    descriptor_test(); refusal_and_guard_test(); replay_and_invalid_test(); flow_test();
    CHECK(current == NULL && wrapper_guard == 0);
    puts("inert exports: descriptor/refusal/guard/isolation/replay/INVALID/fake-flow passed"); return 0;
}
