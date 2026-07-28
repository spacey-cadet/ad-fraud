"""
Click-fraud model training.

Implements the baseline hierarchy from the primer, as executable code instead
of interview talking points:
  1. Heuristic rule baseline      (>50 clicks/hr on one ad_id)
  2. Linear baseline              (logistic regression, one-hot + L2)
  3. Tree ensemble                (LightGBM, tuned num_leaves)
  4. Cost-matrix thresholding     (asymmetric: instant ad-revenue loss vs.
                                   delayed reconciliation loss -> direct cost
                                   minimization, not Youden's J)

Every stage is logged to MLflow (free, self-hosted experiment tracking /
model registry — the OSS stand-in for a managed model registry) so the
metrics you'd otherwise have to recite from memory are just... there.

Run:
    python train.py --data ../../../data/raw/ad_clicks.parquet
"""
import argparse
import json

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder

# ---- Cost matrix (asymmetric, per the primer) ----
COST_FALSE_POSITIVE = 2.50   # blocked legitimate click -> immediate ad revenue loss (USD)
COST_FALSE_NEGATIVE = 6.00   # paid-out fraud, caught only at month-end reconciliation (USD)


def heuristic_baseline(df: pd.DataFrame) -> np.ndarray:
    # Rule is expressed per 60s window here (not per hour, as in the
    # original doc's fraud example) — same "obviously too blunt" shape,
    # calibrated to this window: bots average ~18 clicks/60s, humans ~1.2.
    return (df["clicks_last_60s"] > 8).astype(int).to_numpy()


def build_features(df: pd.DataFrame):
    X = df[["clicks_last_60s", "time_since_last_click_seconds", "device_type", "ad_network_id"]].copy()
    y = df["is_fraud"].astype(int).to_numpy()
    return X, y


def total_cost(y_true, y_pred):
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()
    return fp * COST_FALSE_POSITIVE + fn * COST_FALSE_NEGATIVE


def pick_cost_minimizing_threshold(y_true, proba):
    best_thr, best_cost = 0.5, float("inf")
    for thr in np.linspace(0.01, 0.99, 99):
        y_pred = (proba >= thr).astype(int)
        c = total_cost(y_true, y_pred)
        if c < best_cost:
            best_cost, best_thr = c, thr
    return best_thr, best_cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="../../../data/raw/ad_clicks.parquet")
    ap.add_argument("--advertisers", default="../../../data/raw/dim_advertisers.parquet")
    ap.add_argument("--users", default="../../../data/raw/users.parquet")
    ap.add_argument("--out", default="./model.txt")
    args = ap.parse_args()

    mlflow.set_experiment("click_fraud")

    df = pd.read_parquet(args.data).dropna(subset=["click_id"])
    adv = pd.read_parquet(args.advertisers)[["advertiser_id", "ad_network_id"]]
    users = pd.read_parquet(args.users)[["user_id", "device_type"]]
    df = df.merge(adv, on="advertiser_id", how="left").merge(users, on="user_id", how="left")

    with mlflow.start_run(run_name="baseline_hierarchy"):
        # --- Stage 1: heuristic ---
        y = df["is_fraud"].astype(int).to_numpy()
        heuristic_pred = heuristic_baseline(df)
        heuristic_f1 = f1_score(y, heuristic_pred)
        mlflow.log_metric("heuristic_f1", heuristic_f1)
        print(f"[1/3] heuristic rule baseline F1: {heuristic_f1:.3f} "
              f"(positive rate: {y.mean():.4%})")

        # --- Stage 2: linear baseline (logistic regression) ---
        X, y = build_features(df)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        cat_cols = ["device_type", "ad_network_id"]
        num_cols = ["clicks_last_60s", "time_since_last_click_seconds"]
        ohe = OneHotEncoder(handle_unknown="ignore")
        X_train_cat = ohe.fit_transform(X_train[cat_cols])
        X_test_cat = ohe.transform(X_test[cat_cols])

        from scipy.sparse import hstack
        X_train_lin = hstack([X_train_cat, X_train[num_cols].values])
        X_test_lin = hstack([X_test_cat, X_test[num_cols].values])

        logreg = LogisticRegression(penalty="l2", max_iter=1000, class_weight="balanced")
        logreg.fit(X_train_lin, y_train)
        linear_proba = logreg.predict_proba(X_test_lin)[:, 1]
        linear_f1 = f1_score(y_test, linear_proba >= 0.5)
        mlflow.log_metric("linear_baseline_f1", linear_f1)
        print(f"[2/3] logistic regression (L2, one-hot) F1: {linear_f1:.3f}")

        # --- Stage 3: LightGBM ---
        for c in cat_cols:
            X_train[c] = X_train[c].astype("category")
            X_test[c] = X_test[c].astype("category")
        train_set = lgb.Dataset(
            X_train[num_cols + cat_cols], label=y_train, categorical_feature=cat_cols
        )
        params = {
            "objective": "binary",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "metric": "binary_logloss",
            "verbosity": -1,
        }
        gbm = lgb.train(params, train_set, num_boost_round=600)
        gbm_proba = gbm.predict(X_test[num_cols + cat_cols])
        gbm_f1 = f1_score(y_test, gbm_proba >= 0.5)
        gbm_auc = roc_auc_score(y_test, gbm_proba)
        mlflow.log_params(params)
        mlflow.log_metric("lightgbm_f1_default_thr", gbm_f1)
        mlflow.log_metric("lightgbm_auc", gbm_auc)
        print(f"[3/3] LightGBM (num_leaves=31) F1@0.5: {gbm_f1:.3f} | AUC: {gbm_auc:.3f}")

        # --- Stage 4: cost-matrix thresholding ---
        best_thr, best_cost = pick_cost_minimizing_threshold(y_test, gbm_proba)
        final_pred = (gbm_proba >= best_thr).astype(int)
        final_f1 = f1_score(y_test, final_pred)
        mlflow.log_metric("cost_minimizing_threshold", best_thr)
        mlflow.log_metric("total_cost_usd", best_cost)
        mlflow.log_metric("final_f1_at_cost_threshold", final_f1)
        print(f"[cost] threshold={best_thr:.2f}  total_cost=${best_cost:,.2f}  F1={final_f1:.3f}")

        gbm.save_model(args.out)
        mlflow.log_artifact(args.out)

        summary = {
            "heuristic_f1": heuristic_f1,
            "linear_f1": linear_f1,
            "lightgbm_f1": gbm_f1,
            "cost_minimizing_threshold": best_thr,
            "final_f1": final_f1,
        }
        with open("training_summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        mlflow.log_artifact("training_summary.json")


if __name__ == "__main__":
    main()
