"""Prepare explicit synthetic journal configuration for its isolated CI job."""
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_JOB") != "postgres-provider-journal"):
        raise SystemExit("Requires the isolated journal GitHub Actions job")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
        raise SystemExit("Invalid CI run identity")
    names = ("OMNIFORGE_CONFIG", "OMNIFORGE_JOURNAL_CI_ROOT",
             "OMNIFORGE_JOURNAL_CI_MANIFEST")
    if any(os.environ.get(name) for name in names):
        raise SystemExit("Refusing inherited journal configuration")
    paths = []
    for name in ("RUNNER_TEMP", "GITHUB_WORKSPACE", "GITHUB_ENV", "GITHUB_OUTPUT"):
        raw = os.environ.get(name, "")
        if not raw or any(char in raw for char in ("\n", "\r", "\x00")):
            raise SystemExit("Invalid CI path")
        path = Path(raw)
        if not path.is_absolute() or path.is_symlink():
            raise SystemExit("CI paths must be absolute and not symlinks")
        resolved = path.resolve(strict=True)
        if path != resolved:
            raise SystemExit("CI path aliases are not permitted")
        paths.append(resolved)
    temporary, workspace, environment, output = paths
    if (not temporary.is_dir() or not workspace.is_dir()
            or not environment.is_file()
            or temporary == workspace or workspace in temporary.parents
            or temporary in workspace.parents
            or temporary not in environment.parents or not output.is_file()
            or temporary not in output.parents):
        raise SystemExit("CI temporary files must be isolated from checkout")
    root = Path(tempfile.mkdtemp(prefix="omniforge-journal-ci-", dir=temporary))
    root.chmod(0o700)
    artifacts = root / "artifacts"
    artifacts.mkdir(mode=0o700)
    config = root / "config.json"
    manifest = root / "manifest.json"
    values = {
        config: {
            "database_url": "postgresql+psycopg://omniforge_rebuild_journal_ci:ephemeral-journal-ci-only@127.0.0.1:5432/omniforge_rebuild_journal_ci",
            "artifact_root": str(artifacts),
        },
        manifest: {
            "schema_version": 1,
            "purpose": "omniforge-provider-journal-ci-v1",
            "run_id": run_id,
            "run_attempt": attempt,
            "job": "postgres-provider-journal",
            "root": str(root),
            "config": str(config),
            "workspace": str(workspace),
        },
    }
    for path, value in values.items():
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        path.chmod(0o600)
    exports = dict(zip(names, (config, root, manifest)))
    with environment.open("a", encoding="utf-8") as handle:
        for name, path in exports.items():
            handle.write(f"{name}={path}\n")
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"receipt={root / 'journal-proof.json'}\n")
    print("Synthetic journal CI configuration prepared")


def export_receipt():
    # This mode is selected only after the preparation step succeeded. Revalidate
    # its full context and exact fresh step output before reading any receipt.
    from tests.integration.core.provider_diagnostics_runner import validate_context
    context = validate_context(os.environ)
    expected = context.root / "journal-proof.json"
    if os.environ.get("JOURNAL_RECEIPT_PATH") != str(expected):
        raise SystemExit("Journal receipt unavailable")
    if expected.is_symlink() or expected.resolve(strict=True) != expected:
        raise SystemExit("Journal receipt unavailable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(expected, flags)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise SystemExit("Journal receipt unavailable")
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise SystemExit("Journal receipt unavailable")
    print(json.dumps(json.loads(raw), ensure_ascii=True))


if __name__ == "__main__":
    if sys.argv[1:] == ["--export-receipt"]:
        try:
            export_receipt()
        except (Exception, SystemExit):
            print("Journal receipt unavailable; preceding proof result remains authoritative")
            raise SystemExit(1)
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("Unsupported CI helper mode")
