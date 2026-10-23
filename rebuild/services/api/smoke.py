"""One deterministic, offline health/contract smoke; no server or external I/O."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app import ErrorEnvelope, Health, create_app


def main() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/system/health")
        assert response.status_code == 200
        health = Health.model_validate(response.json())
        assert health.status == "alive" and health.ready is False
        assert health.migration_version is None
        for name in ("database", "artifacts"):
            dependency = getattr(health, name)
            assert dependency.ready is False and dependency.status == "not_connected"
        for name in ("provider", "scheduler"):
            assert getattr(health, name).status == "unverified"
        missing = client.get("/api/v1/notimplemented")
        assert missing.status_code == 404
        error = ErrorEnvelope.model_validate(missing.json())
        assert error.category == "not_found"
        assert str(error.request_id) == missing.headers["X-Request-ID"]
        snapshot = Path(__file__).resolve().parents[2] / "packages/contracts/openapi.json"
        assert client.get("/openapi.json").json() == json.loads(snapshot.read_text(encoding="utf-8"))
    print("PASS: health alive/core unready; disconnected dependencies; safe 404; OpenAPI snapshot matches")


if __name__ == "__main__":
    main()
