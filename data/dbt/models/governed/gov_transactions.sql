{{
  config(
    materialized='view',
    tags=['governed'],
  )
}}

-- Deduplicated transactions. FINAL is what collapses a replay: the canonical
-- table is a ReplacingMergeTree, and without FINAL a re-ingested record shows
-- twice until a background merge happens to run. "Correct after a while" is not
-- a property a revenue figure may have.
--
-- organization_id is selected but never filtered here. The governed query layer
-- injects the tenant predicate; a model that hard-coded one would be a model
-- that silently serves the wrong tenant the day it is reused.

select
    organization_id,
    transaction_id,
    location_id,
    channel_id,
    campaign_id,
    occurred_at,
    ingested_at,
    amount_minor,
    currency,
    line_count,
    lineage_ref,
    mapping_version,
    data_quality_flags
from {{ source('canonical', 'fact_transaction') }} final
