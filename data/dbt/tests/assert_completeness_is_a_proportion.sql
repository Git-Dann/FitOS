-- Completeness outside [0, 1] means the accepted/rejected arithmetic is wrong,
-- which would make every data-quality gap it raises wrong too.

select
    organization_id,
    source_key,
    day,
    completeness
from {{ ref('gov_data_quality') }}
where completeness is not null
  and (completeness < 0 or completeness > 1)
