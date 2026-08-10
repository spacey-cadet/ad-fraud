
  
  create view "warehouse"."main"."stg_ad_clicks__dbt_tmp" as (
    -- Gate 2 lives here: advertiser_id referential integrity against
-- dim_advertisers. A failure means a stale advertiser record, which
-- silently misattributes fraud cost to the wrong account (worse than a
-- duplicate key, because it's silent).
select
    click_id,
    user_id,
    advertiser_id,
    event_ts,
    clicks_last_60s,
    time_since_last_click_seconds,
    is_fraud
from "warehouse"."main"."ad_clicks"
where click_id is not null   -- ingestion gate's 0%-null-tolerance rule, re-enforced in batch
  );
