"""Runtime configuration.

The production guard lives here because it must run before anything serves a
request: a deployment that enables demo identity seeding in production is a
tenancy hole, and it should fail loudly at startup rather than quietly at 3am.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FITOS_", extra="ignore")

    environment: Environment = Environment.LOCAL

    database_url: str = "postgresql+psycopg://fitos_app@127.0.0.1:5432/fitos"

    # Identity is issued by Better Auth and verified here against its JWKS.
    # See docs/adr/0005-auth-provider.md.
    jwks_url: str = "http://127.0.0.1:3000/api/auth/jwks"
    jwt_issuer: str = "https://fitos.local"
    jwt_audience: str = "fitos-api"

    # Development-only identity seeding. Never true in production.
    demo_auth_enabled: bool = False

    @model_validator(mode="after")
    def _forbid_demo_auth_in_production(self) -> Settings:
        if self.environment is Environment.PRODUCTION and self.demo_auth_enabled:
            raise ValueError(
                "FITOS_DEMO_AUTH_ENABLED must not be true when FITOS_ENVIRONMENT=production. "
                "Demo identity seeding bypasses the normal login flow."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION
