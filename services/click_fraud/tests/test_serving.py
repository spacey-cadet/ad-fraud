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

_APP = None


def _load_app():
    # Both services have a serving/app.py — importing both as plain "app"
    # collides in sys.modules across test files. Load each under a unique
    # module name instead. Cached so a second call within this test module
    # doesn't re-run app.py's module-level Prometheus metric registration.
    global _APP
    if _APP is None:
        spec = importlib.util.spec_from_file_location(
            "click_fraud_serving_app", os.path.join(SERVING_DIR, "app.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _APP = module.app
    return _APP


@pytest.fixture(scope="module", autouse=True)
def tiny_model():
    """Train a throwaway model so the API has something to load in CI."""
    model_path = os.path.join(SERVING_DIR, "model.txt")
    os.environ["MODEL_PATH"] = model_path

    n = 200
    rng = np.random.default_rng(0)
    X = pd.DataFrame({
        "clicks_last_60s": rng.integers(0, 30, n),
        "time_since_last_click_seconds": rng.exponential(50, n),
        "device_type": rng.choice(["mobile_ios", "desktop_web"], n),
        "ad_network_id": rng.integers(1, 5, n),
    })
    X["device_type"] = X["device_type"].astype("category")
    X["ad_network_id"] = X["ad_network_id"].astype("category")
    y = (X["clicks_last_60s"] > 15).astype(int)
    train_set = lgb.Dataset(X, label=y, categorical_feature=["device_type", "ad_network_id"])
    gbm = lgb.train({"objective": "binary", "verbosity": -1}, train_set, num_boost_round=10)
    gbm.save_model(model_path)
    yield
    os.remove(model_path)


def test_score_endpoint():
    app = _load_app()
    client = TestClient(app)
    resp = client.post("/score", json={
        "user_id": 1,
        "advertiser_id": 1,
        "ad_network_id": 3,
        "device_type": "mobile_ios",
        "clicks_last_60s": 25,
        "time_since_last_click_seconds": 1.2,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["fraud_probability"] <= 1.0
    assert isinstance(body["is_fraud"], bool)


def test_healthz():
    app = _load_app()
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
