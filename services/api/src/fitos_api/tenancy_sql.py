"""Row-level security, as SQL.

RLS cannot be expressed through the ORM, so it lives here as explicit statements
and is applied by the migrations. Keeping it in one module means "which tables
are protected, and by what policy" has a single answer that can be read in
thirty seconds.

`nullif(..., '')` is not cosmetic: after a rollback the setting is an empty
string rather than unset, and `''::uuid` raises 22P02. Without the nullif the
policy errors instead of denying — which still fails closed, but turns an
unscoped query into a 500 rather than an empty result, and hides the mistake.

The model:

  fitos_owner  owns the schema, runs migrations, is exempt from RLS.
  fitos_app    the application role. NOBYPASSRLS, and no DELETE on the tables
               whose whole purpose is to be a record: audit_events and gaps.

Every org-scoped table is FORCE ROW LEVEL SECURITY so the policy applies even to
the table owner.

Each migration applies the statements for the tables *it* creates. `TABLE_GRANTS`
is the full current picture, used by the test fixture, and
`test_every_org_scoped_table_has_rls` fails if a table is added here without a
policy — or added to the schema without being added here.
"""

from __future__ import annotations

import re

APP_ROLE = "fitos_app"
# Better Auth's role. Separate from the application role because it needs the
# tables the application role must never see: password hashes, refresh tokens
# and the private JWT signing keys (migration 0004).
AUTH_ROLE = "fitos_auth"

# Tables carrying organization_id, with the privileges the application role gets.
#
# Note what is absent: DELETE on audit_events and gaps. A gap is dismissed, not
# deleted — deleting one removes the record that it was ever raised, which is the
# same repudiation problem the audit table has (docs/threat-model.md T13).
TABLE_GRANTS: dict[str, str] = {
    "memberships": "SELECT, INSERT, UPDATE, DELETE",
    "audit_events": "SELECT, INSERT",
    "gaps": "SELECT, INSERT, UPDATE",
    "invitations": "SELECT, INSERT, UPDATE",
    "connections": "SELECT, INSERT, UPDATE, DELETE",
    # Versions, runs, rejections and deliveries are all records of what
    # happened. A record you can delete is a record you cannot rely on.
    "mapping_versions": "SELECT, INSERT, UPDATE",
    "connector_runs": "SELECT, INSERT, UPDATE",
    "quarantined_records": "SELECT, INSERT, UPDATE",
    "webhook_deliveries": "SELECT, INSERT",
}

NO_DELETE_TABLES: tuple[str, ...] = (
    "audit_events",
    "gaps",
    "invitations",
    "mapping_versions",
    "connector_runs",
    "quarantined_records",
    "webhook_deliveries",
)

ORG_SCOPED_TABLES: tuple[str, ...] = tuple(TABLE_GRANTS)

_PASSWORD_PATTERN = re.compile(r"[A-Za-z0-9_.\-]{8,128}")


def create_roles(app_password: str) -> list[str]:
    """Create the application role. NOBYPASSRLS is the whole point.

    CREATE ROLE is DDL and cannot take a bound parameter, so the password is
    interpolated. It is validated first: a value containing a quote or a
    backslash could otherwise close the literal and append arbitrary SQL. The
    password comes from configuration rather than a request, so this is defence
    in depth, not the only control.
    """
    if not app_password or not _PASSWORD_PATTERN.fullmatch(app_password):
        raise ValueError(
            "application role password must be 8-128 chars of [A-Za-z0-9_.-]; "
            "it is interpolated into DDL and must not be able to escape the literal"
        )
    create_role = (
        "DO $$ BEGIN "  # noqa: S608
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{app_password}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; "
        "END IF; END $$;"
    )
    # Create first, then grant. The other order only appears to work against a
    # cluster where the role already exists — which is every cluster a migration
    # has ever been run against twice, and no cluster on its first deploy.
    return [create_role, f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};"]


def create_auth_role(password: str) -> list[str]:
    """Create the identity role. Same validation reasoning as `create_roles`."""
    if not password or not _PASSWORD_PATTERN.fullmatch(password):
        raise ValueError(
            "identity role password must be 8-128 chars of [A-Za-z0-9_.-]; "
            "it is interpolated into DDL and must not be able to escape the literal"
        )
    create_role = (
        "DO $$ BEGIN "  # noqa: S608
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{AUTH_ROLE}') THEN "
        f"CREATE ROLE {AUTH_ROLE} LOGIN PASSWORD '{password}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; "
        "END IF; END $$;"
    )
    return [create_role, f"GRANT USAGE ON SCHEMA public TO {AUTH_ROLE};"]


def grants_for(*tables: str) -> list[str]:
    """Least-privilege grants for the named tables."""
    statements: list[str] = []
    for table in tables:
        privileges = TABLE_GRANTS.get(table, "SELECT, INSERT, UPDATE, DELETE")
        statements.append(f"GRANT {privileges} ON {table} TO {APP_ROLE};")
        if table in NO_DELETE_TABLES:
            statements.append(f"REVOKE DELETE, TRUNCATE ON {table} FROM {APP_ROLE};")
    return statements


def tenant_policy(table: str, *, column: str = "organization_id") -> str:
    """Enable, force and define the isolation policy for one table.

    `column` is `id` for `organizations`, where the row *is* the organization.
    """
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
CREATE POLICY {table}_tenant_isolation ON {table}
  USING (
    {column} = nullif(current_setting('app.current_organization_id', true), '')::uuid
  )
  WITH CHECK (
    {column} = nullif(current_setting('app.current_organization_id', true), '')::uuid
  );
"""


def enable_rls(*tables: str) -> list[str]:
    return [
        tenant_policy(t, column="id" if t == "organizations" else "organization_id") for t in tables
    ]


def all_statements(app_password: str) -> list[str]:
    """Everything, for a schema built from metadata rather than migrations.

    Used by the test fixture. Production applies the per-migration subsets, and
    test_migrations.py asserts the two agree.
    """
    tables = ("organizations", *ORG_SCOPED_TABLES)
    return [
        *create_roles(app_password),
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, users TO {APP_ROLE};",
        *grants_for(*ORG_SCOPED_TABLES),
        *enable_rls(*tables),
        *user_organizations_statements(),
        *data_plane_trigger_statements(),
    ]


# ---------------------------------------------------------------------------
# The one deliberate hole in the wall, and why it is this shape
# ---------------------------------------------------------------------------
#
# "Which organizations do I belong to" cannot be answered inside a tenant scope,
# because the answer spans tenants. It is asked before an organization has been
# chosen — it is the question whose answer lets you choose one.
#
# The tempting fix is to widen the memberships policy with
# `OR user_id = current_setting('app.current_user_id')`. That is a bad trade:
# every query against memberships would then also see the caller's rows in other
# organizations, so an unrelated join could leak one without anybody writing a
# cross-tenant query on purpose.
#
# Instead, one SECURITY DEFINER function, which:
#
#   - answers exactly this question and no other,
#   - returns only the caller's own rows, never another user's,
#   - returns organization identity and role only, no membership internals,
#   - pins search_path, so the definer's rights cannot be turned against it by a
#     shadowing object in a caller-controlled schema.
#
# The API calls it only with the verified `sub`. A caller cannot ask it about
# somebody else, because there is no request field that reaches this argument.

USER_ORGANIZATIONS_FUNCTION = """
CREATE OR REPLACE FUNCTION user_organizations(p_user_id uuid)
RETURNS TABLE (organization_id uuid, slug text, name text, role text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT o.id, o.slug::text, o.name::text, m.role::text
  FROM memberships m
  JOIN organizations o ON o.id = m.organization_id
  WHERE m.user_id = p_user_id
  ORDER BY o.name;
$$;
"""


def user_organizations_statements() -> list[str]:
    return [
        USER_ORGANIZATIONS_FUNCTION,
        "REVOKE ALL ON FUNCTION user_organizations(uuid) FROM PUBLIC;",
        f"GRANT EXECUTE ON FUNCTION user_organizations(uuid) TO {APP_ROLE};",
    ]


# ---------------------------------------------------------------------------
# Triggers: the rules a CHECK constraint cannot express
# ---------------------------------------------------------------------------
#
# A CHECK sees one row at a time and cannot compare OLD with NEW, so "this
# column must not change" is beyond it. Both rules below are that shape.
#
# They live here, next to the policies, for the same reason those do: the test
# fixture builds its schema from `Base.metadata`, which carries constraints and
# indexes but no triggers. A trigger defined only inside a migration is a
# trigger the tests cannot prove — exactly how `uq_gap_dedupe_open` slipped
# through in Phase B. One definition, applied by both paths, and
# `test_the_migration_creates_every_trigger` fails if they diverge.

FREEZE_APPLIED_MAPPING = """
CREATE OR REPLACE FUNCTION mapping_versions_freeze_applied()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF OLD.applied_at IS NOT NULL THEN
    IF NEW.column_map IS DISTINCT FROM OLD.column_map
       OR NEW.required_columns IS DISTINCT FROM OLD.required_columns
       OR NEW.transforms IS DISTINCT FROM OLD.transforms
       OR NEW.target_table IS DISTINCT FROM OLD.target_table
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.resource IS DISTINCT FROM OLD.resource THEN
      RAISE EXCEPTION
        'mapping version % has been applied and cannot be edited; '
        'create a new version instead', OLD.version
        USING ERRCODE = 'restrict_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
"""

FREEZE_FINISHED_RUN = """
CREATE OR REPLACE FUNCTION connector_runs_no_count_rewrite()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  IF OLD.finished_at IS NOT NULL THEN
    IF NEW.records_read IS DISTINCT FROM OLD.records_read
       OR NEW.records_written IS DISTINCT FROM OLD.records_written
       OR NEW.records_quarantined IS DISTINCT FROM OLD.records_quarantined
       OR NEW.outcome IS DISTINCT FROM OLD.outcome THEN
      RAISE EXCEPTION
        'run % has finished; its counts and outcome are final', OLD.id
        USING ERRCODE = 'restrict_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
"""

# (trigger name, table, function) — asserted against pg_trigger by the tests.
DATA_PLANE_TRIGGERS: tuple[tuple[str, str, str], ...] = (
    ("mapping_versions_freeze_applied", "mapping_versions", "mapping_versions_freeze_applied"),
    ("connector_runs_no_count_rewrite", "connector_runs", "connector_runs_no_count_rewrite"),
)


def data_plane_trigger_statements() -> list[str]:
    statements = [FREEZE_APPLIED_MAPPING, FREEZE_FINISHED_RUN]
    for name, table, function in DATA_PLANE_TRIGGERS:
        statements.append(f"DROP TRIGGER IF EXISTS {name} ON {table};")
        statements.append(
            f"CREATE TRIGGER {name} BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}();"
        )
    return statements
