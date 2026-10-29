"""Prepare a fresh, explicitly identified synthetic worker authority CI context.

Private integration preparation: actual CI execution awaits combined review.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time


EXPORTS = ("OMNIFORGE_WORKER_CI_ROOT", "OMNIFORGE_WORKER_CI_CONTEXT",
           "OMNIFORGE_WORKER_CI_MANIFEST")
SOURCE_DIRS = ("infra/core", "migrations", "services", "adapters", "packages",
               "tests/integration")
SOURCE_FILES = ("infra/__init__.py", "tests/__init__.py", "tests/integration/__init__.py", "pyproject.toml", "uv.lock")


def canonical(raw):
    if not isinstance(raw, str) or not raw or any(c in raw for c in "\r\n\x00"):
        raise ValueError("Invalid path")
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError("Noncanonical path")
    return path


def read_regular(path, limit):
    canonical(str(path))
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Invalid file")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Oversized file")
    return raw


def sources(workspace):
    rebuild = canonical(str(workspace / "rebuild"))
    result = {}
    for relative in SOURCE_DIRS:
        directory = canonical(str(rebuild / relative))
        if not directory.is_dir():
            raise ValueError("Missing source directory")
        # Reject symlink entries before walking: rglob alone may skip linked dirs.
        for current, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs + files:
                entry = Path(current) / name
                if entry.is_symlink():
                    raise ValueError("Linked source entry")
            for name in files:
                if name.endswith(".py"):
                    path = Path(current) / name
                    key = path.relative_to(rebuild).as_posix()
                    result[key] = hashlib.sha256(read_regular(path, 4 * 1024 * 1024)).hexdigest()
    for relative in SOURCE_FILES:
        if relative.endswith("__init__.py") and not (rebuild / relative).exists():
            continue
        result[relative] = hashlib.sha256(read_regular(rebuild / relative, 4 * 1024 * 1024)).hexdigest()
    return dict(sorted(result.items()))


def context_paths(env):
    if env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_JOB") != "postgres-worker-authority9":
        raise ValueError("Wrong job")
    if env.get("GITHUB_EVENT_NAME") not in ("pull_request", "push"):
        raise ValueError("Wrong event")
    if any(not re.fullmatch(r"[1-9][0-9]{0,19}", env.get(key, ""))
           for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")):
        raise ValueError("Wrong run identity")
    if not re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")):
        raise ValueError("Wrong revision")
    if any(key.upper().startswith("PG") for key in env) or "OMNIFORGE_CONFIG" in env:
        raise ValueError("Inherited database configuration")
    paths = tuple(canonical(env.get(key)) for key in
                  ("RUNNER_TEMP", "GITHUB_WORKSPACE", "GITHUB_ENV", "GITHUB_OUTPUT"))
    temporary, workspace, environment, output = paths
    if (not temporary.is_dir() or not workspace.is_dir()
            or temporary == workspace or temporary in workspace.parents
            or workspace in temporary.parents or environment == output):
        raise ValueError("Overlapping CI paths")
    for path in (environment, output):
        if temporary not in path.parents or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("Invalid CI output path")
    if environment.samefile(output):
        raise ValueError("Aliased CI output channels")
    return paths


def exclusive_json(path, payload):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        os.chmod(path, 0o600)
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def prepare(env):
    temporary, workspace, environment, output = context_paths(env)
    if any(key in env for key in EXPORTS):
        raise ValueError("Inherited worker context")
    source_hashes = sources(workspace)
    root = Path(tempfile.mkdtemp(prefix="omniforge-worker-authority9-", dir=temporary))
    root.chmod(0o700)
    (root / "artifacts").mkdir(mode=0o700)
    context = {
        "schema_version": 1, "purpose": "omniforge-worker-authority9-ci-v1",
        "job": env["GITHUB_JOB"], "event": env["GITHUB_EVENT_NAME"],
        "run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"],
        "sha": env["GITHUB_SHA"], "root": str(root), "workspace": str(workspace),
        "sources": source_hashes,
    }
    exclusive_json(root / "context.json", context)
    # Manifest is created only by a later reviewed bind step after actual preflight.
    with environment.open("a", encoding="utf-8", newline="\n") as handle:
        for name, path in zip(EXPORTS, (root, root / "context.json", root / "manifest.json")):
            handle.write(f"{name}={path}\n")
        handle.flush()
        os.fsync(handle.fileno())
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"root={root}\n")
        handle.flush()
        os.fsync(handle.fileno())
    return root


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate key")
        value[key] = item
    return value


def bind(env, actual_exit, harness=None):
    if type(actual_exit) is not int or actual_exit != 0:
        raise ValueError("Preflight process did not succeed")
    context_paths(env)
    if harness is None:
        from tests.integration.core import worker_authority_ci as harness
    context = harness.validate_context(env)
    raw = read_regular(context.root / "preflight.json", 131072)
    first = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    fields = {"schema_version", "mode", "status", "context_sha256", "identity", "failures", "pool"}
    if (type(first) is not dict or set(first) != fields
            or type(first["schema_version"]) is not int or first["schema_version"] != 1
            or first["mode"] != "preflight" or first["status"] != "passed"
            or first["context_sha256"] != context.context_sha256 or first["failures"] != []):
        raise ValueError("Preflight receipt did not succeed")
    identity = harness.identity_valid(first["identity"])
    pool = first["pool"]
    if (type(pool) is not dict or set(pool) != {"checked_out", "disposed"}
            or type(pool["checked_out"]) is not int or pool["checked_out"] != 0
            or pool["disposed"] is not True):
        raise ValueError("Preflight resources not settled")
    exclusive_json(context.root / "manifest.json", {
        "schema_version": 1, "context_sha256": context.context_sha256,
        "preflight_sha256": hashlib.sha256(raw).hexdigest(), "cluster": identity["cluster"],
    })
    return harness.bind_context(context)


def child(mode, proof_exit=None, *, launcher=subprocess.Popen, publish=lambda value: None):
    """Bound one root child of the frozen no-descendant harness; no retry loops.

Root reap is not an observation of an empty process group or stopped DB service.
"""
    if os.name != "posix" or mode not in ("preflight", "run", "settlement"):
        raise ValueError("Unsupported controller")
    command = [sys.executable, "-B", "-m", "tests.integration.core.worker_authority_ci", mode]
    if mode == "settlement" and proof_exit is not None:
        if type(proof_exit) is not int or not 0 <= proof_exit <= 255:
            raise ValueError("Invalid observed exit")
        command.extend(["--proof-exit", str(proof_exit)])
    duration = {"preflight": 25, "run": 180, "settlement": 40}[mode]
    started = time.monotonic()
    process = None
    result = dict(exit=None, timed_out=False, reaped=False, elapsed_seconds=None,
                  pid=None, pgid=None, scope="root_only_no_descendant_harness",
                  failures=[], cleanup=[])
    def checkpoint():
        try:
            publish(result)
        except BaseException:
            if "process_receipt_unavailable" not in result["failures"]:
                result["failures"].append("process_receipt_unavailable")
    def failed(label):
        result["failures"].append(label)
        checkpoint()
    checkpoint()
    if result["failures"]:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return result
    try:
        process = launcher(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        result.update(pid=process.pid, pgid=process.pid)
        checkpoint()  # Durable exact acquired identity before the first wait.
        try:
            if not result["failures"]:
                process.wait(timeout=duration)
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            checkpoint()
        except BaseException:
            failed("wait_unconfirmed")
        try:
            process.poll()
        except BaseException:
            failed("poll_unconfirmed")
        if process.returncode is None:
            for label, signum in (("term", signal.SIGTERM), ("kill", signal.SIGKILL)):
                if process.returncode is not None:
                    break
                try:
                    os.killpg(process.pid, signum)
                    result["cleanup"].append(label + "_sent")
                except ProcessLookupError:
                    result["cleanup"].append(label + "_group_absent")
                except BaseException:
                    failed(label + "_unconfirmed")
                checkpoint()
                try:
                    process.wait(timeout=2)
                    result["cleanup"].append(label + "_root_wait_returned")
                except BaseException:
                    failed(label + "_root_wait_unconfirmed")
        result["reaped"] = type(process.returncode) is int
        if result["reaped"]:
            code = process.returncode
            result["exit"] = code if 0 <= code <= 255 else min(255, 128 - code) if code < 0 else 255
        else:
            failed("root_unreaped")
    except BaseException:
        failed("launch_or_identity_unconfirmed")
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        checkpoint()
    return result


def succeeded(observed):
    return (type(observed) is dict and type(observed.get("exit")) is int
            and observed["exit"] == 0 and observed.get("reaped") is True
            and observed.get("timed_out") is False and observed.get("failures") == [])


def control(env, *, runner=child, harness=None):
    """Capture actual subprocess outcomes; preserve failure through settlement."""
    context_paths(env)
    if harness is None:
        from tests.integration.core import worker_authority_ci as harness
    context = harness.validate_context(env)
    # Exclusive marker makes the operation one-shot even after controller failure.
    marker = context.root / "controller-started.json"
    exclusive_json(marker, {"schema_version": 1, "context_sha256": context.context_sha256})
    record = dict(schema_version=1, context_sha256=context.context_sha256,
                  status="failed", preflight=None, proof=None, settlement=None,
                  service_disposition="CI_managed_not_independently_observed")
    bound = False
    def invoke(mode, proof_exit=None):
        if runner is not child:
            return runner(mode) if mode != "settlement" else runner(mode, proof_exit)
        # Each event preserves bounded partial acquisition/cleanup state, even if
        # the controller later dies before its aggregate receipt can be written.
        with (context.root / ("process-" + mode + ".jsonl")).open("x", encoding="utf-8") as handle:
            def publish(value):
                payload = json.dumps(dict(context_sha256=context.context_sha256, mode=mode, outcome=value), sort_keys=True) + "\n"
                if handle.write(payload) != len(payload):
                    raise OSError("Partial process receipt")
                handle.flush()
                os.fsync(handle.fileno())
            return child(mode, proof_exit, publish=publish)
    try:
        record["preflight"] = invoke("preflight")
        if not succeeded(record["preflight"]):
            return 1
        bind(env, record["preflight"]["exit"], harness)
        bound = True
        record["proof"] = invoke("run")
    except BaseException:
        # Missing/rejected result remains unconfirmed; never infer an exit code.
        pass
    finally:
        if bound:
            try:
                proof_exit = record["proof"]["exit"] if record["proof"] else None
                record["settlement"] = invoke("settlement", proof_exit)
            except BaseException:
                pass
        if all(succeeded(record[key]) for key in ("preflight", "proof", "settlement")):
            record["status"] = "processes_succeeded_receipt_validation_pending"
        exclusive_json(context.root / "controller.json", record)
    return 0 if record["status"] == "processes_succeeded_receipt_validation_pending" else 1


def object_file(path, limit=131072):
    return json.loads(read_regular(path, limit), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))


def export_result(env, harness=None):
    """Print only fixed summary fields after independent receipt validation."""
    context_paths(env)
    if harness is None:
        from tests.integration.core import worker_authority_ci as harness
    context = harness.bind_context(harness.validate_context(env))
    record = object_file(context.root / "controller.json")
    if (type(record) is not dict or set(record) != {
            "schema_version", "context_sha256", "status", "preflight", "proof", "settlement", "service_disposition"}
            or type(record["schema_version"]) is not int or record["schema_version"] != 1
            or record["context_sha256"] != context.context_sha256
            or record["status"] != "processes_succeeded_receipt_validation_pending"
            or record["service_disposition"] != "CI_managed_not_independently_observed"):
        raise ValueError("Controller outcome unconfirmed")
    for name in ("preflight", "proof", "settlement"):
        child_result = record[name]
        if (not succeeded(child_result) or set(child_result) != {"exit", "timed_out", "reaped", "elapsed_seconds", "pid", "pgid", "scope", "failures", "cleanup"}
                or type(child_result["pid"]) is not int or child_result["pid"] <= 0
                or type(child_result["pgid"]) is not int or child_result["pgid"] != child_result["pid"]
                or child_result["scope"] != "root_only_no_descendant_harness"
                or child_result["cleanup"] != []
                or type(child_result["elapsed_seconds"]) not in (float, int)
                or not 0 <= child_result["elapsed_seconds"] <= 300):
            raise ValueError("Process outcome unconfirmed")
    settled = object_file(context.root / "settlement.json")
    if (type(settled) is not dict or set(settled) != {
            "schema_version", "mode", "status", "context_sha256", "actual_proof_exit", "failures",
            "inspection", "preservation", "pool", "service_disposition", "external_capture"}
            or type(settled["schema_version"]) is not int or settled["schema_version"] != 1
            or settled["mode"] != "settlement"
            or settled["status"] != "selected_sql_and_sessions_settled_service_unobserved"
            or settled["context_sha256"] != context.context_sha256
            or type(settled["actual_proof_exit"]) is not int or settled["actual_proof_exit"] != 0
            or settled["failures"] != [] or settled["preservation"] is not True
            or settled["external_capture"] != "unknown"
            or settled["service_disposition"] != "CI_managed_not_independently_observed"):
        raise ValueError("Settlement outcome unconfirmed")
    inspection = settled["inspection"]
    pool = settled["pool"]
    if (type(inspection) is not dict or set(inspection) != {"role_exists", "role_login", "sessions"}
            or inspection["role_exists"] is not True or inspection["role_login"] is not False
            or inspection["sessions"] != [] or type(pool) is not dict
            or set(pool) != {"checked_out", "disposed"} or type(pool["checked_out"]) is not int
            or pool["checked_out"] != 0 or pool["disposed"] is not True):
        raise ValueError("Resources not settled")
    proof = harness.parse_proof(read_regular(context.root / "proof.jsonl", 2097152), context)
    final = proof[2]["data"]
    if (final.get("status") != "passed" or type(final.get("candidate_exit")) is not int
            or final["candidate_exit"] != 0 or final.get("failures") != []
            or final.get("external_capture") != "unknown" or final.get("native_execution") != "unproved"
            or type(final["pool"]["checked_out"]) is not int or final["pool"]["checked_out"] != 0
            or final["pool"]["disposed"] is not True):
        raise ValueError("Proof outcome unconfirmed")
    harness.proof_success(final["proof"], proof[1]["data"]["baseline20"])
    # No receipt strings, arbitrary errors, SQL, paths, credentials or raw logs.
    summary = dict(schema_version=1, status="selected_synthetic_sql_and_sessions_verified",
                   commit=env["GITHUB_SHA"], sql_denials=21, receiver_scenarios=7,
                   original_tables_preserved=20, actual_process_exits=[0, 0, 0],
                   checked_out=0, pools_disposed=True, role_login=False, remaining_sessions=0,
                   service_disposition="CI_managed_not_independently_observed",
                   external_capture="unknown", native_execution="unproved")
    print(json.dumps(summary, sort_keys=True))
    return summary


if __name__ == "__main__":
    code = 0
    try:
        if sys.argv[1:] == ["prepare"]:
            prepare(os.environ)
        elif len(sys.argv) == 3 and sys.argv[1] == "bind" and sys.argv[2] == "0":
            bind(os.environ, 0)
        elif sys.argv[1:] == ["control"]:
            code = control(os.environ)
        elif sys.argv[1:] == ["export"]:
            export_result(os.environ)
        else:
            raise ValueError("Unsupported preparation mode")
    except (Exception, SystemExit):
        print("Worker authority CI preparation unavailable")
        raise SystemExit(1)
    raise SystemExit(code)
