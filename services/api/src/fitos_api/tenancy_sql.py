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
}

NO_DELETE_TABLES: tuple[str, ...] = ("audit_events", "gaps", "invitations")

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
    return [f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};", create_role]


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
