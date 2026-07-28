"""
Feature views. `user_behavior_fv` is the *shared* feature set both services
read from — device stability and engagement cadence matter to both a
click-fraud score and a churn score, which is the concrete link between the
two systems the README describes.

`click_fraud_fv` and `churn_fv` are each service's private, high-frequency
features that don't belong in the shared view.
"""
from datetime import timedelta

from feast import FeatureView, Field, FileSource
from feast.types import Bool, Float32, Int64, String

from entities import advertiser, user

users_source = FileSource(
    path="data/raw/users_features.parquet",
    timestamp_field="event_timestamp",
)

user_behavior_fv = FeatureView(
    name="user_behavior",
    entities=[user],
    ttl=timedelta(days=1),
    schema=[
        Field(name="device_type", dtype=String),
        Field(name="tenure_days", dtype=Int64),
        Field(name="sessions_last_28d", dtype=Int64),
        Field(name="watch_minutes_last_28d", dtype=Float32),
    ],
    online=True,
    source=users_source,
    tags={"shared_by": "click_fraud,churn_prediction"},
)

click_fraud_source = FileSource(
    path="data/raw/click_fraud_features.parquet",
    timestamp_field="event_timestamp",
)

click_fraud_fv = FeatureView(
    name="click_fraud_realtime",
    entities=[user, advertiser],
    ttl=timedelta(minutes=10),
    schema=[
        Field(name="clicks_last_60s", dtype=Int64),
        Field(name="time_since_last_click_seconds", dtype=Float32),
    ],
    online=True,
    source=click_fraud_source,
    tags={"owner": "click_fraud", "compute": "flink-equivalent-streaming-window"},
)

churn_source = FileSource(
    path="data/raw/churn_features.parquet",
    timestamp_field="event_timestamp",
)

churn_fv = FeatureView(
    name="churn_batch",
    entities=[user],
    ttl=timedelta(days=2),
    schema=[
        Field(name="support_tickets_last_90d", dtype=Int64),
        Field(name="payment_failed_last_90d", dtype=Bool),
    ],
    online=True,
    source=churn_source,
    tags={"owner": "churn_prediction", "compute": "dbt-batch"},
)
