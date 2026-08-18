-- Every governed transaction must trace back to a raw object and the mapping
-- version that produced it. Without both, a gap raised from this row cannot
-- show its working, and "no gap without evidence" becomes unenforceable one
-- layer above where it was written down.

select
    organization_id,
    transaction_id
from {{ ref('gov_transactions') }}
where lineage_ref = ''
   or lineage_ref is null
   or mapping_version = 0
