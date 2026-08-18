"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Response

from fitos_api import __version__
from fitos_api.auth.tokens import TokenVerifier
from fitos_api.db import configure, session_factory
from fitos_api.health import ReadinessRegistry
from fitos_api.routes import memberships
from fitos_api.settings import Settings

SERVICE = "api"


def create_app(
    registry: ReadinessRegistry | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    # Settings validation is what enforces the production guard: constructing
    # Settings with demo auth enabled in production raises, so the process
    # fails at startup rather than serving with a bypass available.
    settings = settings or Settings()

    app = FastAPI(title="FitOS API", version=__version__)
    app.state.settings = settings
    app.state.readiness = registry if registry is not None else ReadinessRegistry()
    app.state.token_verifier = TokenVerifier(
        jwks_url=settings.jwks_url,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )

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

    app.include_router(memberships.router)
    return app


def bootstrap() -> FastAPI:
    """Entry point for a running process: configure the database, then build."""
    settings = Settings()
    engine = configure(settings.database_url)
    app = create_app(settings=settings)
    app.state.session_factory = session_factory(engine)
    return app


# Module-level app for `uvicorn fitos_api.main:app`. create_engine is lazy, so
# importing this does not open a connection; the first request does.
app = bootstrap()
