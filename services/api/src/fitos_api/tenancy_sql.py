"""Row-level security, as SQL.

RLS cannot be expressed through the ORM, so it lives here as explicit
statements and is applied by the migration. Keeping it in one module means
"which tables are protected, and by what policy" has a single answer that can
be read in thirty seconds.

`nullif(..., '')` is not cosmetic: after a rollback the setting is an empty
string rather than unset, and `''::uuid` raises 22P02. Without the nullif the
policy errors instead of denying — which still fails closed, but turns an
unscoped query into a 500 rather than an empty result, and hides the mistake.

The model:

  fitos_owner  owns the schema, runs migrations, is exempt from RLS.
  fitos_app    the application role. NOBYPASSRLS. INSERT/SELECT only on audit.

Every org-scoped table is FORCE ROW LEVEL SECURITY so the policy applies even
to the table owner, and every policy keys off `app.current_organization_id`,
which db.organization_scope sets with SET LOCAL.
"""

from __future__ import annotations

import re

# Tables carrying organization_id. Adding one without adding it here is caught
# by test_every_org_scoped_table_has_rls.
ORG_SCOPED_TABLES: tuple[str, ...] = ("memberships", "audit_events")

APP_ROLE = "fitos_app"

_TENANT_POLICY = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
CREATE POLICY {table}_tenant_isolation ON {table}
  USING (
    organization_id = nullif(current_setting('app.current_organization_id', true), '')::uuid
  )
  WITH CHECK (
    organization_id = nullif(current_setting('app.current_organization_id', true), '')::uuid
  );
"""

# Organizations are not org-scoped by a column — the row *is* the organization.
# A caller may only see the organization its token names.
_ORGANIZATION_POLICY = """
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS organizations_tenant_isolation ON organizations;
CREATE POLICY organizations_tenant_isolation ON organizations
  USING (id = nullif(current_setting('app.current_organization_id', true), '')::uuid)
  WITH CHECK (id = nullif(current_setting('app.current_organization_id', true), '')::uuid);
"""


def create_roles(app_password: str) -> list[str]:
    """Create the application role. NOBYPASSRLS is the whole point.

    CREATE ROLE is DDL and cannot take a bound parameter, so the password is
    interpolated. It is validated first: a value containing a quote or a
    backslash could otherwise close the literal and append arbitrary SQL. The
    password comes from configuration rather than a request, so this is
    defence in depth, not the only control.
    """
    if not app_password or not re.fullmatch(r"[A-Za-z0-9_.\-]{8,128}", app_password):
        raise ValueError(
            "application role password must be 8-128 chars of [A-Za-z0-9_.-]; "
            "it is interpolated into DDL and must not be able to escape the literal"
        )
    # S608 suppressed with cause: CREATE ROLE is DDL and takes no bound
    # parameters. app_password is validated against a strict character class
    # immediately above so it cannot terminate the literal, and APP_ROLE is a
    # module constant, not input.
    create_role = (
        "DO $$ BEGIN "  # noqa: S608
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{app_password}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; "
        "END IF; END $$;"
    )
    return [create_role]


def grant_privileges() -> list[str]:
    """Least privilege for the application role.

    Note what audit_events does NOT get: UPDATE and DELETE. Retention deletion
    runs under a separate credential and is itself audited.
    """
    return [
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, users, memberships TO {APP_ROLE};",
        f"GRANT SELECT, INSERT ON audit_events TO {APP_ROLE};",
        f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {APP_ROLE};",
    ]


def enable_rls() -> list[str]:
    statements = [_ORGANIZATION_POLICY]
    statements.extend(_TENANT_POLICY.format(table=t) for t in ORG_SCOPED_TABLES)
    return statements


def all_statements(app_password: str) -> list[str]:
    return [*create_roles(app_password), *grant_privileges(), *enable_rls()]
