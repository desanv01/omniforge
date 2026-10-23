"""Create synthetic GitHub Actions configuration outside the source checkout."""
import json
import os
from pathlib import Path
import secrets
import tempfile


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This helper is only for ephemeral GitHub Actions jobs")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    checkout = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    if temporary == checkout or checkout in temporary.parents:
        raise SystemExit("Runner temporary directory must be outside checkout")
    root = Path(tempfile.mkdtemp(prefix="omniforge-core-ci-", dir=temporary))
    root.chmod(0o700)
    for folder in ("staging", "blobs"):
        (root / "artifacts" / folder).mkdir(parents=True)
    token = root / "auth-token"
    with token.open("x", encoding="utf-8") as handle:
        handle.write(secrets.token_urlsafe(48))
    token.chmod(0o600)
    config = root / "config.json"
    with config.open("x", encoding="utf-8") as handle:
        json.dump({
            "database_url": "postgresql+psycopg://omniforge_rebuild:ephemeral-ci-only@127.0.0.1:5432/omniforge_rebuild",
            "artifact_root": str(root / "artifacts"),
        }, handle)
    config.chmod(0o600)
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as handle:
        for name, value in (("OMNIFORGE_CONFIG", config), ("OMNIFORGE_CI_ROOT", root)):
            if "\n" in str(value) or "\r" in str(value):
                raise SystemExit("Invalid runner path")
            handle.write(f"{name}={value}\n")
    print("Synthetic CI configuration created; credentials omitted")


if __name__ == "__main__":
    main()
