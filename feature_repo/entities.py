from feast import Entity, ValueType

user = Entity(
    name="user_id",
    value_type=ValueType.INT64,
    description="Shared entity across click-fraud and churn models — same subscriber base.",
)

advertiser = Entity(
    name="advertiser_id",
    value_type=ValueType.INT64,
    description="Advertiser dimension, used for referential-integrity checks in the batch pipeline.",
)
