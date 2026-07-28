{{ config(materialized='table') }}

-- Batch feature mart consumed by services/churn_prediction/training/train.py
-- and mirrored into the Feast offline store (feature_repo/features.py ::
-- churn_fv). Cancellation labels lag a full billing cycle by design (see
-- data/generate_synthetic_data.py) — this mart is what gets refreshed
-- nightly by the GitHub Actions batch workflow.

select
    u.user_id,
    u.device_type,
    s.as_of_date,
    s.tenure_days,
    s.sessions_last_28d,
    s.watch_minutes_last_28d,
    s.support_tickets_last_90d,
    s.payment_failed_last_90d,
    s.will_cancel_next_cycle
from {{ ref('stg_users') }} u
join {{ ref('stg_subscription_events') }} s using (user_id)
