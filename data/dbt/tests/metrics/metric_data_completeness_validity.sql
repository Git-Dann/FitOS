-- GENERATED FILE — do not edit.
--
-- Produced from data/metrics/definitions/data_completeness.yml by data/metrics/compile.py.
-- Edit the definition and run `pnpm metrics:compile`.

-- Validity for data_completeness@v1.

{{ config(severity='error') }}

-- not_null, between_0_and_1. A value breaking one of these is wrong, not merely weak.
select
    organization_id, source_key,
    (sum(accepted_records) / nullIf(sum(total_records), 0)) as value,
    count(*) as observations
from {{ ref('gov_data_quality') }}
group by organization_id, source_key
having (sum(accepted_records) / nullIf(sum(total_records), 0)) IS NULL
       OR (sum(accepted_records) / nullIf(sum(total_records), 0)) < 0 OR (sum(accepted_records) / nullIf(sum(total_records), 0)) > 1
