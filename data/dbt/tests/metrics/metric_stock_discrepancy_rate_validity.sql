-- GENERATED FILE — do not edit.
--
-- Produced from data/metrics/definitions/stock_discrepancy_rate.yml by data/metrics/compile.py.
-- Edit the definition and run `pnpm metrics:compile`.

-- Validity for stock_discrepancy_rate@v1.

{{ config(severity='error') }}

-- not_null, between_0_and_1. A value breaking one of these is wrong, not merely weak.
select
    organization_id, location_id,
    (countIf(abs(discrepancy) > 0) / nullIf(count(), 0)) as value,
    count(*) as observations
from {{ ref('gov_stock_truth') }}
group by organization_id, location_id
having (countIf(abs(discrepancy) > 0) / nullIf(count(), 0)) IS NULL
       OR (countIf(abs(discrepancy) > 0) / nullIf(count(), 0)) < 0 OR (countIf(abs(discrepancy) > 0) / nullIf(count(), 0)) > 1
