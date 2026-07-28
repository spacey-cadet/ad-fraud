select
    user_id,
    device_type,
    signup_date
from {{ source('raw', 'users') }}
