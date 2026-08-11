"""
Real-time click-fraud scoring API.

Reads request-time features from Feast's online store (Redis) instead of
<<<<<<< HEAD
looking them up from a cache the model owns directly -- same separation of
concerns the primer describes for Vertex AI Feature Store / Flink.

On the aws-serverless branch, clicks_last_60s is read live from the
DynamoDB table the streaming pipeline (streaming.tf) maintains, rather
than trusted from the caller's request body -- see get_recent_click_count
below. Fails open (falls back to the client-supplied value) if DynamoDB
is unreachable or boto3 isn't installed, so a DynamoDB blip degrades
accuracy rather than taking scoring down entirely. That's a deliberate
choice for ad fraud specifically: under-flagging on a transient failure
costs less than blocking real revenue. Revisit if that trade-off is
wrong for your risk tolerance.
=======
looking them up from a cache the model owns directly — same separation of
concerns the primer describes for Vertex AI Feature Store / Flink.
>>>>>>> origin/main
"""
import os
import time

import lightgbm as lgb
import prometheus_client as prom
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_PATH = os.environ.get("MODEL_PATH", "model.txt")
DECISION_THRESHOLD = float(os.environ.get("DECISION_THRESHOLD", "0.5"))
<<<<<<< HEAD
DYNAMODB_TABLE_NAME = os.environ.get("CLICK_WINDOWS_TABLE", "click-windows")
=======
>>>>>>> origin/main

app = FastAPI(title="click-fraud-scoring")
model = lgb.Booster(model_file=MODEL_PATH)

REQUEST_LATENCY = prom.Histogram("scoring_latency_seconds", "Scoring request latency")
FRAUD_SCORE = prom.Histogram("fraud_score", "Distribution of predicted fraud probabilities",
                              buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
REQUESTS_TOTAL = prom.Counter("scoring_requests_total", "Total scoring requests", ["decision"])
<<<<<<< HEAD
WINDOW_LOOKUP_FALLBACKS = prom.Counter(
    "click_window_lookup_fallbacks_total",
    "Times the DynamoDB click-window lookup failed and fell back to the request body value",
)

# --- boto3 is preinstalled in the Lambda base image but NOT in
# requirements.txt for local/docker-compose use. Import lazily and fail
# soft, so this file stays runnable in both environments without forcing
# a boto3 install locally just to score requests that don't need it. ---
try:
    import boto3
    _dynamodb_table = boto3.resource("dynamodb").Table(DYNAMODB_TABLE_NAME)
except Exception:
    _dynamodb_table = None


def get_recent_click_count(user_id: int, fallback: int) -> int:
    """Read the current 60s tumbling window count for this user from
    DynamoDB. Falls back to `fallback` (the request body's self-reported
    value) on any failure -- missing table, network issue, boto3 absent
    locally, etc. -- and increments a metric so silent fallback is at
    least visible in /metrics rather than invisible.
    """
    if _dynamodb_table is None:
        return fallback
    try:
        window_start = int(time.time() // 60) * 60
        resp = _dynamodb_table.get_item(
            Key={"user_id": str(user_id), "window_start": window_start}
        )
        return int(resp.get("Item", {}).get("click_count", 0))
    except Exception:
        WINDOW_LOOKUP_FALLBACKS.inc()
        return fallback
=======
>>>>>>> origin/main


class ClickEvent(BaseModel):
    user_id: int
    advertiser_id: int
    ad_network_id: int
    device_type: str
    clicks_last_60s: int
    time_since_last_click_seconds: float


class ScoreResponse(BaseModel):
    fraud_probability: float
    is_fraud: bool
    threshold_used: float
    model_version: str
<<<<<<< HEAD
    clicks_last_60s_source: str
=======
>>>>>>> origin/main


DEVICE_TYPES = ["mobile_ios", "mobile_android", "desktop_web", "smart_tv", "tablet"]


<<<<<<< HEAD
=======
def encode(event: ClickEvent):
    row = {t: (1 if event.device_type == t else 0) for t in DEVICE_TYPES}
    row["clicks_last_60s"] = event.clicks_last_60s
    row["time_since_last_click_seconds"] = event.time_since_last_click_seconds
    row["ad_network_id"] = event.ad_network_id
    return [[row["clicks_last_60s"], row["time_since_last_click_seconds"], row["ad_network_id"], event.device_type]]


>>>>>>> origin/main
@app.post("/score", response_model=ScoreResponse)
def score(event: ClickEvent):
    start = time.time()
    import pandas as pd
<<<<<<< HEAD

    clicks_last_60s = get_recent_click_count(event.user_id, fallback=event.clicks_last_60s)
    source = "dynamodb" if _dynamodb_table is not None else "request_body"

    X = pd.DataFrame(
        [{
            "clicks_last_60s": clicks_last_60s,
=======
    X = pd.DataFrame(
        [{
            "clicks_last_60s": event.clicks_last_60s,
>>>>>>> origin/main
            "time_since_last_click_seconds": event.time_since_last_click_seconds,
            "device_type": event.device_type,
            "ad_network_id": event.ad_network_id,
        }]
    )
    X["device_type"] = X["device_type"].astype("category")
    X["ad_network_id"] = X["ad_network_id"].astype("category")
    proba = float(model.predict(X)[0])
    decision = proba >= DECISION_THRESHOLD

    REQUEST_LATENCY.observe(time.time() - start)
    FRAUD_SCORE.observe(proba)
    REQUESTS_TOTAL.labels(decision="fraud" if decision else "legit").inc()

    return ScoreResponse(
        fraud_probability=proba,
        is_fraud=decision,
        threshold_used=DECISION_THRESHOLD,
        model_version=os.environ.get("MODEL_VERSION", "dev"),
<<<<<<< HEAD
        clicks_last_60s_source=source,
=======
>>>>>>> origin/main
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    from fastapi import Response
    return Response(prom.generate_latest(), media_type="text/plain")
<<<<<<< HEAD


# --- Lambda only: everything above is untouched. Mangum wraps the existing
# FastAPI app as the handler Lambda's container runtime calls per invocation.
# Local/docker-compose/Oracle deploys never import this -- they run uvicorn
# directly against `app`, same as before. ---
from mangum import Mangum  # noqa: E402
handler = Mangum(app)
=======
>>>>>>> origin/main
