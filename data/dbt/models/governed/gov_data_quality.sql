{{
  config(
    materialized='view',
    tags=['governed', 'data_quality'],
  )
}}

-- data_completeness is a metric like any other. Making it first-class is what
-- lets a data-quality gap suppress a business gap through the same machinery,
-- rather than through a special case somebody has to remember.

with accepted as (
    select
        organization_id,
        source_key,
        toDate(occurred_at) as day,
        count() as accepted_records
    from {{ source('canonical', 'fact_transaction') }} final
    group by organization_id, source_key, day
),

rejected as (
    select
        organization_id,
        source_key,
        toDate(occurred_at) as day,
        count() as rejected_records
    from {{ source('canonical', 'quarantine_record') }} final
    group by organization_id, source_key, day
)

select
    coalesce(accepted.organization_id, rejected.organization_id) as organization_id,
    coalesce(accepted.source_key, rejected.source_key) as source_key,
    coalesce(accepted.day, rejected.day) as day,
    coalesce(accepted.accepted_records, 0) as accepted_records,
    coalesce(rejected.rejected_records, 0) as rejected_records,
    coalesce(accepted.accepted_records, 0) + coalesce(rejected.rejected_records, 0)
        as total_records,
    -- Null when nothing arrived at all. A completeness of 1.0 for a day with no
    -- data is the most dangerous number in the system: it says everything is
    -- fine about a source that has stopped.
    case
        when coalesce(accepted.accepted_records, 0) + coalesce(rejected.rejected_records, 0) = 0
            then null
        else coalesce(accepted.accepted_records, 0)
            / (coalesce(accepted.accepted_records, 0) + coalesce(rejected.rejected_records, 0))
    end as completeness
from accepted
full outer join rejected
    on accepted.organization_id = rejected.organization_id
    and accepted.source_key = rejected.source_key
    and accepted.day = rejected.day
