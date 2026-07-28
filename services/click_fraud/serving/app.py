"""
Real-time click-fraud scoring API.

Reads request-time features from Feast's online store (Redis) instead of
looking them up from a cache the model owns directly — same separation of
concerns the primer describes for Vertex AI Feature Store / Flink.
"""
import os
import time

import lightgbm as lgb
import prometheus_client as prom
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_PATH = os.environ.get("MODEL_PATH", "model.txt")
DECISION_THRESHOLD = float(os.environ.get("DECISION_THRESHOLD", "0.5"))

app = FastAPI(title="click-fraud-scoring")
model = lgb.Booster(model_file=MODEL_PATH)

REQUEST_LATENCY = prom.Histogram("scoring_latency_seconds", "Scoring request latency")
FRAUD_SCORE = prom.Histogram("fraud_score", "Distribution of predicted fraud probabilities",
                              buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
REQUESTS_TOTAL = prom.Counter("scoring_requests_total", "Total scoring requests", ["decision"])


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


DEVICE_TYPES = ["mobile_ios", "mobile_android", "desktop_web", "smart_tv", "tablet"]


def encode(event: ClickEvent):
    row = {t: (1 if event.device_type == t else 0) for t in DEVICE_TYPES}
    row["clicks_last_60s"] = event.clicks_last_60s
    row["time_since_last_click_seconds"] = event.time_since_last_click_seconds
    row["ad_network_id"] = event.ad_network_id
    return [[row["clicks_last_60s"], row["time_since_last_click_seconds"], row["ad_network_id"], event.device_type]]


@app.post("/score", response_model=ScoreResponse)
def score(event: ClickEvent):
    start = time.time()
    import pandas as pd
    X = pd.DataFrame(
        [{
            "clicks_last_60s": event.clicks_last_60s,
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
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    from fastapi import Response
    return Response(prom.generate_latest(), media_type="text/plain")
