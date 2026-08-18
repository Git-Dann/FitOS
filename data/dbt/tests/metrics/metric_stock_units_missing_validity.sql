-- GENERATED FILE — do not edit.
--
-- Produced from data/metrics/definitions/stock_units_missing.yml by data/metrics/compile.py.
-- Edit the definition and run `pnpm metrics:compile`.

-- Validity for stock_units_missing@v1.

{{ config(severity='error') }}

-- not_null, non_negative. A value breaking one of these is wrong, not merely weak.
select
    organization_id, location_id,
    (sum(if(discrepancy > 0, discrepancy, 0))) as value,
    count(*) as observations
from {{ ref('gov_stock_truth') }}
group by organization_id, location_id
having (sum(if(discrepancy > 0, discrepancy, 0))) IS NULL
       OR (sum(if(discrepancy > 0, discrepancy, 0))) < 0
