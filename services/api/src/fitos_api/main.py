"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Response

from fitos_api import __version__
from fitos_api.health import ReadinessRegistry

SERVICE = "api"


def create_app(registry: ReadinessRegistry | None = None) -> FastAPI:
    app = FastAPI(title="FitOS API", version=__version__)
    app.state.readiness = registry if registry is not None else ReadinessRegistry()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE, "version": __version__}

    @app.get("/ready")
    async def ready(response: Response) -> dict[str, object]:
        status, checks = await app.state.readiness.evaluate()
        # 503 on degraded so an orchestrator withholds traffic rather than
        # routing into a service that cannot answer.
        response.status_code = 200 if status == "ready" else 503
        return {
            "status": status,
            "service": SERVICE,
            "checks": {name: check.as_dict() for name, check in checks.items()},
        }

    return app


app = create_app()
