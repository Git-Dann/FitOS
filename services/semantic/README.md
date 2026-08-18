# services/semantic — Cube Core

Mounted into the `cube` container as `/cube/conf` by
`infra/compose/docker-compose.yml`.

Empty in Phase A. Cube models, tenant access policies and pre-aggregations are
authored in Phase D, generated from the metric contract in
`docs/data-contracts.md` §5 so a model cannot drift from its contract without
failing CI. See [ADR 0004](../../docs/adr/0004-semantic-layer.md), which also
records the pre-authorised fallback if the dbt–ClickHouse–Cube combination
proves unsafe.
