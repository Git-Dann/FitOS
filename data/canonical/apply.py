"""Apply the canonical schema to ClickHouse.

An explicit step, because the alternative bites. The first version of this
existed only inside a pytest fixture, so the tables appeared as a side effect of
running the tests. That works on a developer's machine, where the schema is
already there from last time, and fails on a fresh CI ClickHouse the moment
anything runs *before* the tests — which is exactly what happened: `dbt build`
ran first and could not find a single source table.

Schema creation is a deployment step. The tests use this same function so the
two cannot drift, but they are no longer the thing that performs it.

Idempotent: every statement is `CREATE ... IF NOT EXISTS`, so running it against
an existing database is a no-op rather than an error. That is what makes it safe
to run at the start of every CI job and every local `pnpm dev:infra`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from canonical.schema import all_statements, table_names

# A database name reaches DDL by interpolation, because an identifier cannot be
# a bound parameter. It comes from configuration rather than a request, so this
# is defence in depth — but it is cheap, and "only an operator can set it" is
# what everybody says about the argument that later gets wired to a form.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")

# http and https only. A `file:` URL here would make the applier read the local
# disk and report it as a server response.
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def apply(
    *,
    url: str,
    user: str,
    password: str,
    database: str = "fitos",
) -> list[str]:
    """Create every canonical table. Returns the tables that now exist."""
    if not _IDENTIFIER.fullmatch(database):
        raise ValueError(f"{database!r} is not a valid database identifier")

    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"{scheme!r} is not an allowed scheme; use http or https")

    params = urllib.parse.urlencode({"user": user, "password": password})
    endpoint = f"{url.rstrip('/')}/?{params}"

    for statement in all_statements(database):
        # S310 warns that a URL could carry file: or a custom scheme. The
        # scheme is checked against an allowlist above, which is the control it
        # is asking for.
        request = urllib.request.Request(endpoint, data=statement.encode())  # noqa: S310
        try:
            urllib.request.urlopen(request, timeout=60)  # noqa: S310
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:500]
            # Naming the statement matters: a ClickHouse DDL error quotes the
            # column it disliked but not which table it was building.
            first_line = statement.strip().splitlines()[0]
            raise RuntimeError(f"failed applying {first_line!r}: {detail}") from exc

    # `database` is validated as an identifier above; ClickHouse's HTTP
    # interface takes no bound parameters for a query like this.
    listing = f"SELECT name FROM system.tables WHERE database='{database}' ORDER BY name"  # noqa: S608
    check = urllib.request.Request(endpoint, data=listing.encode())  # noqa: S310
    with urllib.request.urlopen(check, timeout=30) as response:  # noqa: S310
        names: list[str] = response.read().decode().split()
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the FitOS canonical schema.")
    parser.add_argument(
        "--url", default=os.environ.get("FITOS_CLICKHOUSE_URL", "http://127.0.0.1:8123/")
    )
    parser.add_argument("--user", default=os.environ.get("FITOS_CLICKHOUSE_USER", "fitos"))
    parser.add_argument(
        "--password", default=os.environ.get("FITOS_CLICKHOUSE_PASSWORD", "fitos_local_only")
    )
    parser.add_argument("--database", default=os.environ.get("FITOS_CLICKHOUSE_DB", "fitos"))
    args = parser.parse_args(argv)

    present = apply(url=args.url, user=args.user, password=args.password, database=args.database)

    expected = set(table_names())
    missing = expected - set(present)
    if missing:
        print(f"error: these tables were not created: {sorted(missing)}", file=sys.stderr)
        return 1

    print(f"applied {len(expected)} canonical tables to {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
