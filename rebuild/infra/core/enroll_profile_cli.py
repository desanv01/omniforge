"""Explicit terminal enrollment entrypoint; import performs no configuration/I/O.

Actual invocation needs separately authorized local setup. Automated checks must
inject factories, bridge and input; this module never discovers keys or config.
"""

import getpass
import json
from pathlib import Path
import re
import sys
import warnings
from uuid import UUID

from adapters.secrets.enrollment import EnrollmentReceipt, EnrollmentRequest
from adapters.secrets.store import SecretValue


_FLAGS = ("--config", "--principal-id", "--case-id", "--profile-id",
          "--operation-id", "--expected-revision")


def _error(stream, message):
    try:
        stream.write(message + "\n")
        stream.flush()
    except (Exception, KeyboardInterrupt):
        pass


def _arguments(arguments):
    # Exact pairs only: reject aliases, duplicates, unknown flags and arbitrary
    # reference/token/key arguments without reflecting submitted argument text.
    if len(arguments) != 2 * len(_FLAGS):
        raise ValueError("Invalid invocation")
    fields = {}
    for index in range(0, len(arguments), 2):
        flag, value = arguments[index:index + 2]
        if flag not in _FLAGS or flag in fields or type(value) is not str:
            raise ValueError("Invalid invocation")
        fields[flag] = value
    if set(fields) != set(_FLAGS):
        raise ValueError("Invalid invocation")
    path = fields["--config"]
    if not 1 <= len(path) <= 4096 or "\x00" in path or not Path(path).is_absolute():
        raise ValueError("Explicit absolute config location required")
    ids = {}
    for name in ("--operation-id", "--principal-id", "--case-id", "--profile-id"):
        text = fields[name]
        parsed = UUID(text)
        if str(parsed) != text:
            raise ValueError("Canonical UUID required")
        ids[name] = parsed
    revision = fields["--expected-revision"]
    if not re.fullmatch(r"[1-9][0-9]{0,9}", revision) or int(revision) > 2147483647:
        raise ValueError("Positive bounded revision required")
    return Path(path), EnrollmentRequest(
        operation_id=ids["--operation-id"], principal_id=ids["--principal-id"],
        case_id=ids["--case-id"], profile_id=ids["--profile-id"],
        expected_revision=int(revision))


def _engine(config_path):
    # Only the explicitly chosen file, never Settings.from_env or auth-token files.
    from services.api.settings import Settings
    from services.api.db import engine_for
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return engine_for(Settings(database_url=data["database_url"],
                               artifact_root=Path(data["artifact_root"])))


def _store():
    from adapters.secrets.windows import WindowsSecretStore
    return WindowsSecretStore()


def _bridge(engine, **arguments):
    from infra.core.enroll_profile import enroll_profile
    return enroll_profile(engine, **arguments)


def _tuple(item):
    return (item.operation_id, item.principal_id, item.case_id, item.profile_id,
            item.expected_revision)


def _hidden(reader, errors, label):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return reader(label, stream=errors)


def run(argv=None, *, stdin=None, stdout=None, stderr=None, prompt=None,
        engine_factory=None, store_factory=None, bridge=None):
    """Invoke once with hidden auth then bridge-managed hidden credential input.

    Returns 0 for a validated attached receipt, 2 for argument/terminal rejection,
    1 for failures. No retry, activation, credential cleanup or recovery command.
    """
    argv = sys.argv[1:] if argv is None else argv
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    token = None
    engine = None
    supplied_values = []
    attempted = False
    try:
        try:
            config_path, request = _arguments(argv)
        except Exception:
            _error(stderr, "Invalid enrollment arguments; explicit config, IDs and revision required.")
            return 2
        if not stdin.isatty() or not stderr.isatty():
            _error(stderr, "Profile enrollment requires an interactive terminal.")
            return 2
        # Fail before input/config access if output is already unusable.
        stdout.write("")
        stdout.flush()
        reader = getpass.getpass if prompt is None else prompt
        token = _hidden(reader, stderr, "Local bearer token (hidden): ")
        if (type(token) is not str or not 1 <= len(token) <= 256
                or not all(32 < ord(character) < 127 for character in token)):
            raise ValueError("Invalid local authentication input")
        engine = (_engine if engine_factory is None else engine_factory)(config_path)
        store = (_store if store_factory is None else store_factory)()
        requested_tuple = _tuple(request)
        credential_prompted = False

        def hidden_credential():
            nonlocal credential_prompted
            raw = None
            try:
                if credential_prompted:
                    raise ValueError("Repeated credential input refused")
                credential_prompted = True
                raw = _hidden(reader, stderr, "New provider credential (hidden): ")
                if type(raw) is not str or not raw or raw.isspace() or len(raw) > 2560:
                    raise ValueError("Invalid credential input")
                value = SecretValue(raw.encode("utf-8", errors="strict"))
                supplied_values.append(value)
                return value
            finally:
                raw = None

        attempted = True
        receipt = (_bridge if bridge is None else bridge)(
            engine, bearer_token=token, request=request, store=store,
            hidden_input=hidden_credential)
        if (type(receipt) is not EnrollmentReceipt or _tuple(receipt) != requested_tuple
                or _tuple(request) != requested_tuple or receipt.status != "attached"
                or type(receipt.attached_revision) is not int
                or receipt.attached_revision != requested_tuple[-1] + 1):
            raise ValueError("Invalid enrollment receipt")
        # Close before printing success; dispose failures cannot become success.
        owned_engine, engine = engine, None
        owned_engine.dispose()
        result = {"schema_version": 1, "operation_id": str(receipt.operation_id),
                  "case_id": str(receipt.case_id), "profile_id": str(receipt.profile_id),
                  "expected_revision": receipt.expected_revision,
                  "attached_revision": receipt.attached_revision, "status": "attached"}
        stdout.write(json.dumps(result, sort_keys=True) + "\n")
        stdout.flush()
        return 0
    except (Exception, KeyboardInterrupt):
        if attempted:
            _error(stderr, "Profile enrollment outcome is uncertain; do not retry automatically.")
        else:
            _error(stderr, "Profile enrollment did not complete.")
        return 1
    finally:
        token = None
        for value in supplied_values:
            value.clear()
        if engine is not None:
            try:
                engine.dispose()
            except (Exception, KeyboardInterrupt):
                _error(stderr, "Local resource closure failed; inspect privately without retrying enrollment.")


if __name__ == "__main__":
    raise SystemExit(run())
