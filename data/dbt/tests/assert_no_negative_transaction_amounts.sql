-- A negative amount on a transaction is a sign convention that differs from
-- ours. Returns are their own fact; accepting a negative here silently halves
-- somebody's revenue, and nothing downstream would ever flag it.
--
-- A dbt test passes when it returns no rows.

select
    organization_id,
    transaction_id,
    amount_minor
from {{ ref('gov_transactions') }}
where amount_minor < 0
