"""The migration and the models must not drift.

The test suite builds its schema from `Base.metadata`, but production builds it
from Alembic. If those two diverge, every tenancy test passes against a schema
that is not the one deployed — which is worse than having no tests, because it
looks like coverage.

This runs the real migration against a real database and compares the result to
the metadata, so drift is caught the day it appears rather than the day it
matters.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import ADMIN_URL, requires_db
from fitos_api.models import Base
from sqlalchemy import create_engine, inspect, text

pytestmark = requires_db

API_ROOT = Path(__file__).resolve().parents[1]
APP_PASSWORD = "migration_test_only"
AUTH_PASSWORD = "migration_test_only"


@pytest.fixture
def migrated_database() -> Iterator[str]:
    """A database built by `alembic upgrade head`, not by create_all."""
    assert ADMIN_URL
    name = f"fitos_mig_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env={
            **os.environ,
            "FITOS_MIGRATION_DATABASE_URL": url,
            "FITOS_APP_ROLE_PASSWORD": APP_PASSWORD,
            "FITOS_AUTH_ROLE_PASSWORD": AUTH_PASSWORD,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"

    yield url

    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def test_the_migration_creates_every_table_the_models_declare(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    actual = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    engine.dispose()

    missing = expected - actual
    assert not missing, f"models declare tables the migration does not create: {sorted(missing)}"


def test_the_migration_creates_every_column_the_models_declare(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    inspector = inspect(engine)
    problems: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        actual = {c["name"] for c in inspector.get_columns(table_name)}
        expected = {c.name for c in table.columns}
        for column in sorted(expected - actual):
            problems.append(f"{table_name}.{column} missing from the migration")
    engine.dispose()
    assert not problems, "\n".join(problems)


def test_the_migration_creates_every_index_the_models_declare(migrated_database: str) -> None:
    """Columns matching is not enough.

    `uq_gap_dedupe_open` was written into migration 0002 and not into the model,
    so the metadata-built test schema had no dedupe protection at all and the
    dedupe test failed against a schema production did not have. Comparing only
    tables and columns missed it.
    """
    engine = create_engine(migrated_database)
    inspector = inspect(engine)
    problems: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        actual = {i["name"] for i in inspector.get_indexes(table_name)}
        actual |= {c["name"] for c in inspector.get_unique_constraints(table_name)}
        expected = {str(i.name) for i in table.indexes if i.name is not None}
        for index in sorted(expected - actual):
            problems.append(f"{table_name}.{index} missing from the migration")
    engine.dispose()
    assert not problems, "\n".join(problems)


def test_the_migrated_schema_enforces_rls(migrated_database: str) -> None:
    """The protection has to come from the migration, not from the test setup.

    Without this, the tenancy suite could be passing purely because conftest
    applies the policies itself.
    """
    engine = create_engine(migrated_database)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN "
                "('organizations','memberships','audit_events','gaps','invitations')"
            )
        ).all()
    engine.dispose()

    assert len(rows) == 5
    for name, enabled, forced in rows:
        assert enabled, f"{name} has no RLS after migration"
        assert forced, f"{name} does not FORCE RLS after migration"


def test_the_migration_grants_the_app_role_no_way_to_rewrite_audit(
    migrated_database: str,
) -> None:
    engine = create_engine(migrated_database)
    with engine.connect() as conn:
        granted = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'fitos_app' AND table_name = 'audit_events'"
                )
            ).all()
        }
    engine.dispose()

    assert granted == {"SELECT", "INSERT"}, f"unexpected audit privileges: {sorted(granted)}"


def test_the_migration_refuses_to_run_without_an_app_role_password() -> None:
    """A default password in a migration becomes a production password."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env={
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "FITOS_APP_ROLE_PASSWORD",
                "FITOS_AUTH_ROLE_PASSWORD",
                "FITOS_MIGRATION_DATABASE_URL",
            }
        }
        | {"FITOS_MIGRATION_DATABASE_URL": ADMIN_URL or ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "FITOS_APP_ROLE_PASSWORD" in result.stderr


def test_downgrade_is_refused_because_it_would_destroy_the_audit_trail() -> None:
    """T13. Rolling this migration back would drop audit_events."""
    import importlib.util

    path = API_ROOT / "migrations" / "versions" / "0001_tenancy_and_audit.py"
    spec = importlib.util.spec_from_file_location("migration_0001", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(NotImplementedError, match="audit trail"):
        module.downgrade()


def test_the_migration_creates_the_cross_tenant_function_with_a_pinned_search_path(
    migrated_database: str,
) -> None:
    """SECURITY DEFINER without a pinned search_path is a privilege-escalation bug.

    The function runs as its owner, which is the role that owns the schema. If
    an attacker can get an object of theirs resolved ahead of `public`, the body
    executes their code with the owner's rights. `SET search_path` in the
    definition is what closes that, so it is asserted here rather than assumed
    from having written it once.
    """
    engine = create_engine(migrated_database)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'user_organizations'")
        ).one()
    engine.dispose()

    security_definer, config = row
    assert security_definer, "user_organizations must be SECURITY DEFINER to answer across tenants"
    assert config is not None, "SECURITY DEFINER function with no pinned search_path"
    assert any(c.startswith("search_path=") for c in config), config


def test_the_cross_tenant_function_is_not_executable_by_everyone(
    migrated_database: str,
) -> None:
    """PUBLIC EXECUTE is the default on a new function and must be revoked."""
    engine = create_engine(migrated_database)
    with engine.connect() as conn:
        public_can_execute = conn.execute(
            text("SELECT has_function_privilege('public', 'user_organizations(uuid)', 'EXECUTE')")
        ).scalar_one()
        app_can_execute = conn.execute(
            text(
                "SELECT has_function_privilege('fitos_app', 'user_organizations(uuid)', 'EXECUTE')"
            )
        ).scalar_one()
    engine.dispose()

    assert not public_can_execute, "PUBLIC can execute the cross-tenant function"
    assert app_can_execute, "the application role cannot execute it, so the switcher is broken"


def test_the_application_role_cannot_read_the_signing_keys(migrated_database: str) -> None:
    """RELEASE GATE. An injection in the API must not reach the private keys.

    `jwks` holds the private halves of the JWT signing keys and `accounts` holds
    password hashes and OAuth refresh tokens. Every API request runs as
    `fitos_app`. If that role can select from either table, the blast radius of
    any SQL injection in the API includes minting tokens for anyone.
    """
    engine = create_engine(migrated_database)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'fitos_app' "
                "AND table_name IN ('jwks','accounts','sessions','verifications')"
            )
        ).all()
    engine.dispose()

    assert rows == [], f"the application role can reach identity tables: {rows}"


def test_the_identity_role_can_do_its_job(migrated_database: str) -> None:
    """The counterpart. Revoking too much is also a bug, just a louder one."""
    engine = create_engine(migrated_database)
    with engine.connect() as conn:
        granted = {
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'fitos_auth'"
                )
            ).all()
        }
    engine.dispose()

    for table in ("jwks", "accounts", "sessions", "verifications", "users"):
        assert (table, "SELECT") in granted, f"the identity role cannot read {table}"
        assert (table, "INSERT") in granted, f"the identity role cannot write {table}"


def test_the_migration_refuses_to_run_without_an_identity_role_password() -> None:
    """Same reasoning as the application role: no default becomes a production one."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env={k: v for k, v in os.environ.items() if k != "FITOS_AUTH_ROLE_PASSWORD"}
        | {
            "FITOS_MIGRATION_DATABASE_URL": ADMIN_URL or "",
            "FITOS_APP_ROLE_PASSWORD": APP_PASSWORD,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "FITOS_AUTH_ROLE_PASSWORD" in result.stderr


def test_a_role_is_created_before_it_is_granted_anything() -> None:
    """Statement order, because the wrong order only fails on a fresh cluster.

    `GRANT USAGE ... TO fitos_app` before `CREATE ROLE fitos_app` succeeds on
    every cluster where the role already exists — which is every cluster a
    migration has run against twice, and no cluster on its first deploy. It was
    written that way and passed for exactly that reason, until migration 0004
    added a second role and the first real run failed.
    """
    from fitos_api.tenancy_sql import create_auth_role, create_roles

    for statements in (create_roles("valid_password"), create_auth_role("valid_password")):
        create_index = next(i for i, s in enumerate(statements) if "CREATE ROLE" in s)
        grant_index = next(i for i, s in enumerate(statements) if "GRANT USAGE" in s)
        assert create_index < grant_index, statements
