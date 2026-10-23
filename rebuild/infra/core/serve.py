"""Loopback-only prototype entry point. Tokens never appear in access logs."""
import argparse
import uvicorn
from services.api.settings import Settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if Settings.from_env() is None or not 1024 <= args.port <= 65535:
        raise SystemExit("Explicit private configuration and unprivileged port required")
    uvicorn.run("services.api.app:app", host="127.0.0.1", port=args.port, access_log=False)
