import importlib.util
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

SERVING_DIR = os.path.join(os.path.dirname(__file__), "..", "serving")
sys.path.insert(0, SERVING_DIR)


def _load_app():
    spec = importlib.util.spec_from_file_location(
        "churn_serving_app", os.path.join(SERVING_DIR, "app.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


@pytest.fixture(scope="module", autouse=True)
def tiny_model():
    model_path = os.path.join(SERVING_DIR, "model.txt")
    os.environ["MODEL_PATH"] = model_path

    n = 200
    rng = np.random.default_rng(0)
    X = pd.DataFrame({
        "tenure_days": rng.integers(1, 900, n),
        "sessions_last_28d": rng.integers(0, 20, n),
        "watch_minutes_last_28d": rng.normal(300, 100, n).clip(min=0),
        "support_tickets_last_90d": rng.integers(0, 5, n),
        "device_type": rng.choice(["mobile_ios", "desktop_web"], n),
        "payment_failed_last_90d": rng.choice([True, False], n),
    })
    X["device_type"] = X["device_type"].astype("category")
    X["payment_failed_last_90d"] = X["payment_failed_last_90d"].astype("category")
    y = (X["sessions_last_28d"] < 5).astype(int)
    train_set = lgb.Dataset(
        X, label=y, categorical_feature=["device_type", "payment_failed_last_90d"]
    )
    gbm = lgb.train({"objective": "binary", "verbosity": -1}, train_set, num_boost_round=10)
    gbm.save_model(model_path)
    yield
    os.remove(model_path)


def test_score_endpoint():
    app = _load_app()
    client = TestClient(app)
    resp = client.post("/score", json={
        "tenure_days": 30,
        "sessions_last_28d": 1,
        "watch_minutes_last_28d": 20.0,
        "support_tickets_last_90d": 3,
        "device_type": "mobile_ios",
        "payment_failed_last_90d": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["cancel_probability"] <= 1.0
