from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fitos_api.health import ReadinessRegistry
from fitos_api.main import create_app


def test_health_is_liveness_only() -> None:
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "api", "version": "0.0.0"}


def test_ready_with_no_dependencies_is_ready() -> None:
    client = TestClient(create_app())
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_ready_reports_503_and_names_the_failing_dependency() -> None:
    registry = ReadinessRegistry()

    async def down() -> bool:
        return False

    async def up() -> bool:
        return True

    registry.register("postgres", down)
    registry.register("clickhouse", up)

    r = TestClient(create_app(registry)).get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["postgres"]["ok"] is False
    assert body["checks"]["clickhouse"]["ok"] is True


def test_a_raising_probe_never_leaks_its_message() -> None:
    registry = ReadinessRegistry()

    async def leaky() -> bool:
        raise ConnectionError("postgres://fitos:hunter2@db.internal:5432/fitos unreachable")

    registry.register("postgres", leaky)
    r = TestClient(create_app(registry)).get("/ready")

    assert r.status_code == 503
    assert r.json()["checks"]["postgres"]["detail"] == "ConnectionError"
    assert "hunter2" not in r.text
    assert "db.internal" not in r.text


def test_duplicate_probe_registration_is_rejected() -> None:
    registry = ReadinessRegistry()

    async def probe() -> bool:
        return True

    registry.register("postgres", probe)
    with pytest.raises(ValueError, match="duplicate readiness probe"):
        registry.register("postgres", probe)
