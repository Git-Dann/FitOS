-- The join must take the most recent snapshot at or before the check. A
-- snapshot taken after the count would make the count look wrong when it was
-- the system that had not caught up — raising a gap against the person who did
-- the work.

select
    organization_id,
    check_id,
    checked_at,
    snapshot_at
from {{ ref('gov_stock_truth') }}
where snapshot_at is not null
  and snapshot_at > checked_at
