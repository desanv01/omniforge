#ifndef OF_SLOT_INERT_EXPORTS_H
#define OF_SLOT_INERT_EXPORTS_H
#include "owned_slot.h"

/* Wire schema: six header words, then these values IN ORDER. All words LE u32.
 * Values are C expressions; independent expectations live in slot_artifact.py. */
#define OF_INERT_FIELDS(X) \
 X(version, OF_VERSION) X(machine, 0x8664u) X(little_endian, 1u) X(cdecl_x64, 1u) \
 X(pointer_size, sizeof(void *)) X(pointer_align, __alignof(void *)) \
 X(handle_size, sizeof(HANDLE)) X(handle_align, __alignof(HANDLE)) \
 X(size_t_size, sizeof(SIZE_T)) X(size_t_align, __alignof(SIZE_T)) \
 X(i32_size, sizeof(int32_t)) X(i32_align, __alignof(int32_t)) X(i32_signed, ((int32_t)-1 < 0)) \
 X(u32_size, sizeof(uint32_t)) X(u32_align, __alignof(uint32_t)) X(u32_unsigned, ((uint32_t)-1 > 0)) \
 X(u64_size, sizeof(uint64_t)) X(u64_align, __alignof(uint64_t)) X(u64_unsigned, ((uint64_t)-1 > 0)) \
 X(wchar_size, sizeof(WCHAR)) X(wchar_align, __alignof(WCHAR)) X(wchar_unsigned, ((WCHAR)-1 > 0)) \
 X(dword_size, sizeof(DWORD)) X(dword_align, __alignof(DWORD)) X(dword_unsigned, ((DWORD)-1 > 0)) \
 X(long_size, sizeof(LONG)) X(long_align, __alignof(LONG)) X(long_signed, ((LONG)-1 < 0)) \
 X(slot_capacity, OF_SLOT_CAPACITY) X(slot_size, sizeof(OF_SLOT)) X(slot_align, __alignof(OF_SLOT)) \
 X(arena_capacity, OF_ARENA_CAPACITY) X(arena_offset, offsetof(OF_SLOT, arena)) \
 X(arena_alignment, 8u) X(record_size, sizeof(OF_RECORD)) \
 X(records, OF_RECORDS) X(normal, OF_NORMAL_RECORDS) X(cleanup, OF_CLEANUP_RECORDS) \
 X(cleanup_buckets, OF_CLEANUP_BUCKETS) X(wait_credits, 8u) X(active_credits, 8u) X(exit_credits, 1u) \
 X(creation_flags, OF_CREATION_FLAGS) X(kill_on_close, OF_KILL_ON_CLOSE) \
 X(uuid_bytes, sizeof(((OF_ID *)0)->operation)) X(generation_bytes, sizeof(((OF_ID *)0)->generation)) \
 X(uuid_convention, 1u) X(utf16le, 1u) X(text_units, sizeof(((OF_LAUNCH *)0)->interpreter) / sizeof(WCHAR)) X(text_arrays, 4u) X(handle_count, OF_HANDLE_COUNT) \
 X(id_size, sizeof(OF_ID)) X(id_align, __alignof(OF_ID)) \
 X(id_operation, offsetof(OF_ID, operation)) X(id_generation, offsetof(OF_ID, generation)) X(id_role, offsetof(OF_ID, role)) \
 X(launch_size, sizeof(OF_LAUNCH)) X(launch_align, __alignof(OF_LAUNCH)) \
 X(launch_interpreter, offsetof(OF_LAUNCH, interpreter)) X(launch_script, offsetof(OF_LAUNCH, script)) \
 X(launch_directory, offsetof(OF_LAUNCH, directory)) X(launch_system_root, offsetof(OF_LAUNCH, system_root)) X(launch_target, offsetof(OF_LAUNCH, target)) \
 X(request_size, sizeof(OF_REQUEST)) X(request_align, __alignof(OF_REQUEST)) \
 X(request_sequence, offsetof(OF_REQUEST, sequence)) X(request_action, offsetof(OF_REQUEST, action)) \
 X(request_index, offsetof(OF_REQUEST, index)) X(request_parameter, offsetof(OF_REQUEST, parameter)) X(request_launch, offsetof(OF_REQUEST, launch)) \
 X(result_size, sizeof(OF_RESULT)) X(result_align, __alignof(OF_RESULT)) \
 X(result_code, offsetof(OF_RESULT, code)) X(result_error, offsetof(OF_RESULT, error)) \
 X(result_raw, offsetof(OF_RESULT, raw)) X(result_value, offsetof(OF_RESULT, value)) X(result_replay, offsetof(OF_RESULT, replay)) \
 X(snapshot_size, sizeof(OF_SNAPSHOT)) X(snapshot_align, __alignof(OF_SNAPSHOT)) \
 X(snapshot_id, offsetof(OF_SNAPSHOT, id)) X(snapshot_next_sequence, offsetof(OF_SNAPSHOT, next_sequence)) \
 X(snapshot_record_count, offsetof(OF_SNAPSHOT, record_count)) X(snapshot_normal_count, offsetof(OF_SNAPSHOT, normal_count)) \
 X(snapshot_cleanup_count, offsetof(OF_SNAPSHOT, cleanup_count)) X(snapshot_uncertain, offsetof(OF_SNAPSHOT, uncertain)) \
 X(snapshot_handles, offsetof(OF_SNAPSHOT, handles)) X(snapshot_life, offsetof(OF_SNAPSHOT, life)) \
 X(snapshot_attr_life, offsetof(OF_SNAPSHOT, attr_life)) X(snapshot_process_possible, offsetof(OF_SNAPSHOT, process_possible)) \
 X(snapshot_root_signaled, offsetof(OF_SNAPSHOT, root_signaled)) X(snapshot_zero_active_observed, offsetof(OF_SNAPSHOT, zero_active_observed)) X(snapshot_last, offsetof(OF_SNAPSHOT, last)) \
 X(code_ok, OF_OK) X(code_failed, OF_FAILED) X(code_invalid, OF_INVALID) X(code_busy, OF_BUSY) X(code_stale, OF_STALE) X(code_full, OF_FULL) X(code_unknown, OF_UNKNOWN) \
 X(action_job, OF_JOB) X(action_limit_set, OF_LIMIT_SET) X(action_limit_get, OF_LIMIT_GET) X(action_standard, OF_STANDARD) \
 X(action_attr_init, OF_ATTR_INIT) X(action_attr_update, OF_ATTR_UPDATE) X(action_process, OF_PROCESS) X(action_member, OF_MEMBER) \
 X(action_resume, OF_RESUME) X(action_terminate, OF_TERMINATE) X(action_wait, OF_WAIT) X(action_active, OF_ACTIVE) X(action_exit, OF_EXIT) X(action_attr_delete, OF_ATTR_DELETE) X(action_close, OF_CLOSE) \
 X(resource_job, OF_JOB_HANDLE) X(resource_stdin, OF_STDIN_HANDLE) X(resource_stdout, OF_STDOUT_HANDLE) X(resource_stderr, OF_STDERR_HANDLE) X(resource_process, OF_PROCESS_HANDLE) X(resource_thread, OF_THREAD_HANDLE) \
 X(life_absent, OF_ABSENT) X(life_open, OF_OPEN) X(life_closed, OF_CLOSED) X(life_close_failed, OF_CLOSE_FAILED) \
 X(attr_absent, OF_ATTR_ABSENT) X(attr_initializing, OF_ATTR_INITIALIZING) X(attr_ready, OF_ATTR_READY) X(attr_init_failed, OF_ATTR_INIT_FAILED) X(attr_destroying, OF_ATTR_DESTROYING) X(attr_destroyed, OF_ATTR_DESTROYED) \
 X(target_wait, OF_DUMMY_WAIT) X(target_tree, OF_DUMMY_TREE) X(target_settlement, OF_DUMMY_SETTLEMENT) \
 X(role_child, 1u) X(role_authority, 2u) X(role_settlement, 3u)

#define OF_FIELD_ENUM(name, value) OF_D_##name,
enum OF_INERT_FIELD { OF_INERT_FIELDS(OF_FIELD_ENUM) OF_D_COUNT };
#undef OF_FIELD_ENUM
#define OF_INERT_WORDS (6u + OF_D_COUNT)
#define OF_INERT_BYTES (4u * OF_INERT_WORDS)
#ifdef OF_INERT_BUILD
#define OF_EXPORT __declspec(dllexport)
#else
#define OF_EXPORT
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* Trusted owned data buffers only. No function-pointer/API-table arguments. */
OF_EXPORT int32_t __cdecl of_inert_descriptor_v1(void *, uint32_t bytes);
OF_EXPORT int32_t __cdecl of_inert_init_v1(OF_SLOT *, uint64_t capacity, const OF_ID *);
OF_EXPORT int32_t __cdecl of_inert_apply_v1(OF_SLOT *, const OF_ID *, const OF_REQUEST *, OF_RESULT *);
OF_EXPORT int32_t __cdecl of_inert_snapshot_v1(OF_SLOT *, const OF_ID *, OF_SNAPSHOT *);
#ifdef __cplusplus
}
#endif
#endif
