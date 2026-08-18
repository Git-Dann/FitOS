-- GENERATED FILE — do not edit.
--
-- Produced from data/metrics/definitions/stock_discrepancy_rate.yml by data/metrics/compile.py.
-- Edit the definition and run `pnpm metrics:compile`.

-- Sufficiency for stock_discrepancy_rate@v1.

{{ config(severity='warn') }}

-- denominator_min_30. A warning, not an error: a small sample is a correct value over few observations, and failing the build for it would break every small location. The hard rule lives in the detector, which refuses to raise a gap from an insufficient sample.
select
    organization_id, location_id,
    (countIf(abs(discrepancy) > 0) / nullIf(count(), 0)) as value,
    count(*) as observations
from {{ ref('gov_stock_truth') }}
group by organization_id, location_id
having count(*) < 30
