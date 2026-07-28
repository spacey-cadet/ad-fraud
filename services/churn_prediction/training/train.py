"""
Subscription-cancellation (churn) model training.

Batch counterpart to services/click_fraud/training/train.py — same
baseline-hierarchy discipline, applied to the label-delayed batch case
instead of the low-latency streaming case.

Reads directly from the dbt-built DuckDB mart, so this script only runs
meaningfully after:
    cd services/churn_prediction/dbt && dbt run
"""
import argparse
import json

import duckdb
import lightgbm as lgb
import mlflow
import pandas as pd
from scipy.sparse import hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder


def load_mart(warehouse_path: str) -> pd.DataFrame:
    con = duckdb.connect(warehouse_path, read_only=True)
    df = con.execute("select * from churn_features").fetchdf()
    con.close()
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default="../../../data/warehouse.duckdb")
    ap.add_argument("--out", default="./model.txt")
    args = ap.parse_args()

    mlflow.set_experiment("churn_prediction")

    df = load_mart(args.warehouse)
    y = df["will_cancel_next_cycle"].astype(int).to_numpy()

    num_cols = ["tenure_days", "sessions_last_28d", "watch_minutes_last_28d",
                "support_tickets_last_90d"]
    cat_cols = ["device_type", "payment_failed_last_90d"]
    X = df[num_cols + cat_cols].copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    with mlflow.start_run(run_name="churn_baseline_hierarchy"):
        # --- linear baseline ---
        ohe = OneHotEncoder(handle_unknown="ignore")
        X_train_cat = ohe.fit_transform(X_train[cat_cols].astype(str))
        X_test_cat = ohe.transform(X_test[cat_cols].astype(str))
        X_train_lin = hstack([X_train_cat, X_train[num_cols].values])
        X_test_lin = hstack([X_test_cat, X_test[num_cols].values])

        logreg = LogisticRegression(max_iter=1000, class_weight="balanced")
        logreg.fit(X_train_lin, y_train)
        linear_f1 = f1_score(y_test, logreg.predict(X_test_lin))
        mlflow.log_metric("linear_baseline_f1", linear_f1)
        print(f"[1/2] logistic regression F1: {linear_f1:.3f}  "
              f"(positive rate: {y.mean():.4%})")

        # --- LightGBM ---
        for c in cat_cols:
            X_train[c] = X_train[c].astype("category")
            X_test[c] = X_test[c].astype("category")

        train_set = lgb.Dataset(X_train, label=y_train, categorical_feature=cat_cols)
        params = {
            "objective": "binary",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "metric": "binary_logloss",
            "verbosity": -1,
        }
        gbm = lgb.train(params, train_set, num_boost_round=400)
        proba = gbm.predict(X_test)
        gbm_f1 = f1_score(y_test, proba >= 0.5)
        gbm_auc = roc_auc_score(y_test, proba)
        mlflow.log_params(params)
        mlflow.log_metric("lightgbm_f1", gbm_f1)
        mlflow.log_metric("lightgbm_auc", gbm_auc)
        print(f"[2/2] LightGBM F1@0.5: {gbm_f1:.3f} | AUC: {gbm_auc:.3f}")

        gbm.save_model(args.out)
        mlflow.log_artifact(args.out)

        with open("training_summary.json", "w") as f:
            json.dump({"linear_f1": linear_f1, "lightgbm_f1": gbm_f1, "auc": gbm_auc}, f, indent=2)
        mlflow.log_artifact("training_summary.json")


if __name__ == "__main__":
    main()
