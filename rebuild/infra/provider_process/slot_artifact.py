"""Explicit injected artifact admission. No loader/prototypes or client Backend.

Receipt assertions come from trusted reviewed build/storage custody, not filesystem
verification. Fakes cannot prove real artifact identity or solve loader publication.
"""
from dataclasses import dataclass
from pathlib import PureWindowsPath
import re
import struct
from threading import Lock

from .contracts import NativeUnavailable


class ArtifactError(RuntimeError):
    """Fixed safe codes only; no injected exception text."""


# Independent MSVC-x64 calculation, not generated from C descriptor output:
# id ends52 -> api56; handles144; launch400..4500; command4500..12692;
# environment12692..14740; explicit padding14740..14744; arena..80280;
# 96 records of64 ->86424 (already8-aligned). Never traverse opaque OF_SLOT.
_EXPECTED = (
    ("version", 1), ("machine", 0x8664), ("little_endian", 1), ("cdecl_x64", 1),
    ("pointer_size", 8), ("pointer_align", 8), ("handle_size", 8), ("handle_align", 8),
    ("size_t_size", 8), ("size_t_align", 8), ("i32_size", 4), ("i32_align", 4), ("i32_signed", 1),
    ("u32_size", 4), ("u32_align", 4), ("u32_unsigned", 1),
    ("u64_size", 8), ("u64_align", 8), ("u64_unsigned", 1),
    ("wchar_size", 2), ("wchar_align", 2), ("wchar_unsigned", 1),
    ("dword_size", 4), ("dword_align", 4), ("dword_unsigned", 1),
    ("long_size", 4), ("long_align", 4), ("long_signed", 1),
    ("slot_capacity", 131072), ("slot_size", 86424), ("slot_align", 8),
    ("arena_capacity", 65536), ("arena_offset", 14744), ("arena_alignment", 8),
    ("record_size", 64), ("records", 96), ("normal", 64), ("cleanup", 32),
    ("cleanup_buckets", 11), ("wait_credits", 8), ("active_credits", 8), ("exit_credits", 1),
    ("creation_flags", 0x08080404), ("kill_on_close", 0x2000),
    ("uuid_bytes", 16), ("generation_bytes", 16), ("uuid_convention", 1),
    ("utf16le", 1), ("text_units", 512), ("text_arrays", 4), ("handle_count", 6),
    ("id_size", 36), ("id_align", 4), ("id_operation", 0), ("id_generation", 16), ("id_role", 32),
    ("launch_size", 4100), ("launch_align", 4), ("launch_interpreter", 0), ("launch_script", 1024),
    ("launch_directory", 2048), ("launch_system_root", 3072), ("launch_target", 4096),
    ("request_size", 32), ("request_align", 8), ("request_sequence", 0), ("request_action", 8),
    ("request_index", 12), ("request_parameter", 16), ("request_launch", 24),
    ("result_size", 32), ("result_align", 8), ("result_code", 0), ("result_error", 4),
    ("result_raw", 8), ("result_value", 16), ("result_replay", 24),
    ("snapshot_size", 184), ("snapshot_align", 8), ("snapshot_id", 0), ("snapshot_next_sequence", 40),
    ("snapshot_record_count", 48), ("snapshot_normal_count", 52), ("snapshot_cleanup_count", 56),
    ("snapshot_uncertain", 60), ("snapshot_handles", 64), ("snapshot_life", 112),
    ("snapshot_attr_life", 136), ("snapshot_process_possible", 140), ("snapshot_root_signaled", 144),
    ("snapshot_zero_active_observed", 148), ("snapshot_last", 152),
    ("code_ok", 0), ("code_failed", 1), ("code_invalid", 2), ("code_busy", 3),
    ("code_stale", 4), ("code_full", 5), ("code_unknown", 6),
    ("action_job", 1), ("action_limit_set", 2), ("action_limit_get", 3), ("action_standard", 4),
    ("action_attr_init", 5), ("action_attr_update", 6), ("action_process", 7), ("action_member", 8),
    ("action_resume", 9), ("action_terminate", 10), ("action_wait", 11), ("action_active", 12),
    ("action_exit", 13), ("action_attr_delete", 14), ("action_close", 15),
    ("resource_job", 0), ("resource_stdin", 1), ("resource_stdout", 2), ("resource_stderr", 3),
    ("resource_process", 4), ("resource_thread", 5),
    ("life_absent", 0), ("life_open", 1), ("life_closed", 2), ("life_close_failed", 3),
    ("attr_absent", 0), ("attr_initializing", 1), ("attr_ready", 2), ("attr_init_failed", 3),
    ("attr_destroying", 4), ("attr_destroyed", 5), ("target_wait", 1), ("target_tree", 2),
    ("target_settlement", 3), ("role_child", 1), ("role_authority", 2), ("role_settlement", 3),
)
FIELD_COUNT = 136
WORD_COUNT = 142
BYTE_COUNT = 568
_HEADER = (0x4942464F, 1, BYTE_COUNT, WORD_COUNT, 6, FIELD_COUNT)
EXPORTS = ("of_inert_descriptor_v1", "of_inert_init_v1", "of_inert_apply_v1", "of_inert_snapshot_v1")
_ROOTS = {}  # process-lifetime roots; no production release/unload/retry API
_RESERVATION_LOCK = Lock()  # only guards check/insert, never injected callbacks


def validate_descriptor(data):
    if type(data) is not bytes or len(data) != BYTE_COUNT:
        raise ArtifactError("descriptor_size")
    words = struct.unpack("<" + "I" * WORD_COUNT, data)
    if len(_EXPECTED) != FIELD_COUNT or words[:6] != _HEADER:
        raise ArtifactError("descriptor_header")
    for actual, (_, expected) in zip(words[6:], _EXPECTED, strict=True):
        if actual != expected:
            raise ArtifactError("abi_mismatch")
    return tuple(words)  # immutable metadata only, no declarations synthesized


def _digest(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _absolute(value):
    if type(value) is not str or not value or any(ord(c) < 32 for c in value):
        return False
    p = PureWindowsPath(value)
    return (bool(re.match(r"^[A-Za-z]:\\", value)) and p.is_absolute() and str(p) == value
            and not p.is_reserved() and all(part not in (".", "..") and part == part.rstrip(" .")
                and re.fullmatch(r"[A-Za-z0-9_ .-]+", part) is not None for part in p.parts[1:]))


@dataclass(frozen=True)
class Receipt:
    path: str
    sha256: str
    size: int
    sources: tuple  # exact sorted (relative path, SHA256) pairs
    dependencies: tuple  # sorted exact absolute path/hash/size closure
    storage_attestation: str  # trusted Main-reviewed immutable custody ID
    build_id: str
    target: str = "windows-x64-inert-v1"
    toolset: str = "14.44.35207"
    compiler: str = "19.44.35227.0"
    sdk: str = "10.0.26100.0"
    configuration: str = "Release-C11-W4-WX-MT-guardcf"
    python: str = "3.11-x64"
    dependency_policy: str = "reviewed-exact-closure-no-search"
    exports: tuple = EXPORTS
    schema: int = 1

    def validate(self):
        if (not _absolute(self.path) or not _digest(self.sha256) or type(self.size) is not int
                or not 0 < self.size <= (1 << 32) or type(self.schema) is not int or self.schema != 1):
            raise ArtifactError("receipt_identity")
        for name in ("storage_attestation", "build_id"):
            v = getattr(self, name)
            if type(v) is not str or not 1 <= len(v) <= 128 or re.fullmatch(r"[A-Za-z0-9_.:-]+", v) is None:
                raise ArtifactError("receipt_provenance")
        expected = ("windows-x64-inert-v1", "14.44.35207", "19.44.35227.0", "10.0.26100.0",
                    "Release-C11-W4-WX-MT-guardcf", "3.11-x64", "reviewed-exact-closure-no-search")
        actual = (self.target, self.toolset, self.compiler, self.sdk, self.configuration, self.python, self.dependency_policy)
        if any(type(v) is not str for v in actual) or actual != expected or type(self.exports) is not tuple or self.exports != EXPORTS:
            raise ArtifactError("receipt_target")
        if type(self.sources) is not tuple or not 1 <= len(self.sources) <= 32:
            raise ArtifactError("receipt_sources")
        names = []
        for entry in self.sources:
            if type(entry) is not tuple or len(entry) != 2:
                raise ArtifactError("receipt_sources")
            name, digest = entry
            if (type(name) is not str or re.fullmatch(r"[A-Za-z0-9_./-]+", name) is None
                    or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/")) or not _digest(digest)):
                raise ArtifactError("receipt_sources")
            names.append(name)
        if names != sorted(set(names)):
            raise ArtifactError("receipt_sources")
        if type(self.dependencies) is not tuple or len(self.dependencies) > 32:
            raise ArtifactError("receipt_dependencies")
        paths = []
        for entry in self.dependencies:
            if (type(entry) is not tuple or len(entry) != 3 or not _absolute(entry[0])
                    or not _digest(entry[1]) or type(entry[2]) is not int or not 0 < entry[2] <= (1 << 32)):
                raise ArtifactError("receipt_dependencies")
            paths.append(entry[0].casefold())
        if paths != sorted(set(paths)) or self.path.casefold() in paths:
            raise ArtifactError("receipt_dependencies")


@dataclass(frozen=True)
class Loaded:
    """Trusted injected return; exports tuple in EXACT EXPORTS order, no lookup."""
    module: object
    exports: tuple
    receipt: Receipt


class Lease:
    """Rooted even on rejection. No client construction or slot-call methods."""
    def __init__(self, receipt, loader):
        self._receipt, self._loader = receipt, loader
        self._state = "selected"
        self._returned = None
        self._output = bytearray(BYTE_COUNT)
        self._descriptor = None

    @property
    def state(self):
        return self._state

    @property
    def descriptor(self):
        if self._state != "pinned_validated":
            raise ArtifactError("artifact_unvalidated")
        return self._descriptor


def select(receipt, *, loader=None):
    if loader is None:
        raise NativeUnavailable("inert artifact loader unavailable")
    if type(receipt) is not Receipt or not callable(loader):
        raise ArtifactError("artifact_contract")
    receipt.validate()
    key = receipt.path.casefold()
    # Allocate before locking: no constructor, loader, descriptor or other injected
    # callback can reenter while the non-reentrant reservation lock is held.
    lease = Lease(receipt, loader)
    with _RESERVATION_LOCK:
        if key in _ROOTS:
            raise ArtifactError("artifact_already_selected")
        _ROOTS[key] = lease  # indivisible reservation/root BEFORE loader entry
    lease._state = "loading"
    try:
        lease._returned = loader(receipt)
    except BaseException:
        # A module may exist without a published Python object. Never retry/unload.
        lease._state = "load_unknown"
        raise ArtifactError("loader_return_unknown") from None
    # A returned module/object is rooted even if the returned contract is invalid.
    lease._state = "rejected_pinned"
    try:
        loaded = lease._returned
        if (type(loaded) is not Loaded or loaded.module is None or type(loaded.receipt) is not Receipt
                or loaded.receipt != receipt or type(loaded.exports) is not tuple
                or len(loaded.exports) != 4 or not all(callable(v) for v in loaded.exports)):
            raise ArtifactError("loaded_contract")
        # Descriptor only. Never invoke init/apply/snapshot in this slice.
        status = loaded.exports[0](lease._output, BYTE_COUNT)
        if type(status) is not int or status != 0:
            raise ArtifactError("descriptor_status")
        lease._descriptor = validate_descriptor(bytes(lease._output))
    except BaseException:
        raise ArtifactError("artifact_rejected_pinned") from None
    lease._state = "pinned_validated"
    return lease
