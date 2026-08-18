{{
  config(
    materialized='view',
    tags=['governed', 'retail_pack'],
  )
}}

-- The Stock Truth Gap input: what the system believed against what somebody
-- actually counted.
--
-- ASOF LEFT JOIN, which is exactly "the most recent snapshot at or before this
-- check". Two reasons it is the right tool rather than a clever one:
--
-- 1. The semantics are the requirement. A snapshot taken *after* the count
--    would make a correct count look wrong when it was the system that had not
--    caught up — raising a gap against the person who did the work.
-- 2. ClickHouse refuses an inequality in a plain JOIN ON, so the alternative is
--    an equi-join plus a windowed argMax, which computes the same thing less
--    clearly and reads every snapshot for every variant to do it.
--
-- LEFT, not inner: a variant with no snapshot at all is a real and interesting
-- case — it is one the inventory feed has never covered — and an inner join
-- would delete the evidence of it.
--
-- `join_use_nulls` is not optional here, and its absence is a bug that ships
-- looking correct. ClickHouse fills an unmatched LEFT JOIN row with *type
-- defaults* rather than NULL, so a variant with no snapshot comes back as
-- "the system believed 0 units, at 1970-01-01" — a plausible-looking row
-- reporting a phantom surplus equal to whatever was counted, rather than an
-- obviously absent one. With nulls on, the absence is visible and the CASE
-- below can mean what it says.
--
-- The setting is written into the query rather than passed as a dbt model
-- config: a config setting applies when the view is *created*, and a view runs
-- its own query later. It has to travel with the SELECT.

with checks as (
    select
        organization_id,
        location_id,
        product_variant_id,
        check_id,
        occurred_at as checked_at,
        observed_quantity,
        lineage_ref,
        mapping_version
    from {{ source('canonical', 'fact_stock_check') }} final
),

snapshots as (
    select
        organization_id,
        location_id,
        product_variant_id,
        occurred_at as snapshot_at,
        system_quantity
    from {{ source('canonical', 'fact_inventory_snapshot') }} final
)

select
    checks.organization_id as organization_id,
    checks.location_id as location_id,
    checks.product_variant_id as product_variant_id,
    checks.check_id as check_id,
    checks.checked_at as checked_at,
    checks.observed_quantity as observed_quantity,
    checks.lineage_ref as lineage_ref,
    checks.mapping_version as mapping_version,
    snapshots.snapshot_at as snapshot_at,
    snapshots.system_quantity as system_quantity,
    snapshots.system_quantity - checks.observed_quantity as discrepancy,
    -- Null rather than zero when there is nothing to compare against. Zero
    -- would read as "no discrepancy" and quietly hide every variant the
    -- inventory feed has never covered.
    case
        when snapshots.snapshot_at is null then null
        when snapshots.system_quantity = 0 then null
        else (snapshots.system_quantity - checks.observed_quantity)
            / snapshots.system_quantity
    end as discrepancy_rate
from checks
asof left join snapshots
    on checks.organization_id = snapshots.organization_id
    and checks.location_id = snapshots.location_id
    and checks.product_variant_id = snapshots.product_variant_id
    and snapshots.snapshot_at <= checks.checked_at
settings join_use_nulls = 1
