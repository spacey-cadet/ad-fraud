"""
Batch-scoring API for churn. Unlike click-fraud, this is intentionally not
optimized for per-request latency: it's the API a nightly job or an
internal dashboard calls, not something in the ad-serving hot path.
"""
import os

import lightgbm as lgb
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_PATH = os.environ.get("MODEL_PATH", "model.txt")
app = FastAPI(title="churn-scoring")
model = lgb.Booster(model_file=MODEL_PATH)


class UserFeatures(BaseModel):
    tenure_days: int
    sessions_last_28d: int
    watch_minutes_last_28d: float
    support_tickets_last_90d: int
    device_type: str
    payment_failed_last_90d: bool


class ScoreResponse(BaseModel):
    cancel_probability: float
    will_likely_cancel: bool


@app.post("/score", response_model=ScoreResponse)
def score(f: UserFeatures):
    X = pd.DataFrame([f.model_dump()])
    X["device_type"] = X["device_type"].astype("category")
    X["payment_failed_last_90d"] = X["payment_failed_last_90d"].astype("category")
    proba = float(model.predict(X)[0])
    return ScoreResponse(cancel_probability=proba, will_likely_cancel=proba >= 0.5)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
