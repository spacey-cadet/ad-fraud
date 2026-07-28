select
    user_id,
    cast(as_of_date as date) as as_of_date,
    tenure_days,
    sessions_last_28d,
    watch_minutes_last_28d,
    support_tickets_last_90d,
    payment_failed_last_90d,
    will_cancel_next_cycle
from {{ source('raw', 'subscription_events') }}
