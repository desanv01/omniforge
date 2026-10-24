"""Validate or copy a selected private directory bundle; no database import."""
import argparse
import json

from packages.contracts.export.portable import BundleError, blob_bytes, read_bundle, write_bundle

if __name__ == "__main__":
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("validate", "roundtrip"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        manifest = read_bundle(args.source)
        if args.action == "roundtrip":
            if args.destination is None:
                parser.error("roundtrip requires a destination")
            blobs = {item.sha256: blob_bytes(args.source, item) for item in manifest.artifacts}
            write_bundle(args.destination, manifest, blobs)
        print(json.dumps({"validated": True, "schema_version": manifest.schema_version,
                          "artifacts": len(manifest.artifacts), "origins": len(manifest.associations)}))
    except BundleError as exc:
        raise SystemExit("Bundle rejected: " + exc.code) from None
