"""Generate from actual API and pinned local tooling; retain bundled MIT notice."""
import hashlib
import json
from pathlib import Path
import subprocess

from services.api.app import create_app

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    schema = root / "packages/contracts/openapi.json"
    schema.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tool = root / "infra/core/client-tooling/node_modules/@hey-api/openapi-ts"
    subprocess.run(["node", str(tool / "bin/run.js"), "-i", "packages/contracts/openapi.json",
                    "-o", "packages/contracts/generated", "-c", "@hey-api/client-fetch"], cwd=root, check=True)
    notice = (tool / "LICENSE.md").read_text(encoding="utf-8")
    (root / "packages/contracts/generated/THIRD_PARTY_NOTICES.txt").write_text(
        "Bundled Hey API fetch/core runtime from @hey-api/openapi-ts 0.99.0\n" + notice, encoding="utf-8")
    print("OpenAPI SHA256 " + hashlib.sha256(schema.read_bytes()).hexdigest())
