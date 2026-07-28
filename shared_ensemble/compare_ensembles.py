"""
Executable version of the primer's "Track 1 Addendum" table: bagging vs.
boosting vs. stacking vs. blending vs. voting, run against real data instead
of recited from memory.

This is what ties the two services together conceptually, not just via a
shared feature store: both click_fraud and churn_prediction are instances of
"which ensemble family fixes which statistical problem," and this script
answers that question for both datasets side by side.

Run:
    python compare_ensembles.py --dataset click_fraud
    python compare_ensembles.py --dataset churn
"""
import argparse

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import KFold, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def load_click_fraud():
    df = pd.read_parquet("../data/raw/ad_clicks.parquet").dropna(subset=["click_id"])
    adv = pd.read_parquet("../data/raw/dim_advertisers.parquet")[["advertiser_id", "ad_network_id"]]
    users = pd.read_parquet("../data/raw/users.parquet")[["user_id", "device_type"]]
    df = df.merge(adv, on="advertiser_id", how="left").merge(users, on="user_id", how="left")
    num_cols = ["clicks_last_60s", "time_since_last_click_seconds"]
    cat_cols = ["device_type", "ad_network_id"]
    y = df["is_fraud"].astype(int).to_numpy()
    return df, num_cols, cat_cols, y


def load_churn():
    import duckdb
    con = duckdb.connect("../data/warehouse.duckdb", read_only=True)
    df = con.execute("select * from churn_features").fetchdf()
    con.close()
    num_cols = ["tenure_days", "sessions_last_28d", "watch_minutes_last_28d",
                "support_tickets_last_90d"]
    cat_cols = ["device_type", "payment_failed_last_90d"]
    y = df["will_cancel_next_cycle"].astype(int).to_numpy()
    return df, num_cols, cat_cols, y


def to_dense_matrix(df, num_cols, cat_cols, ohe=None, fit=False):
    if fit:
        ohe = OneHotEncoder(handle_unknown="ignore")
        cat = ohe.fit_transform(df[cat_cols].astype(str))
    else:
        cat = ohe.transform(df[cat_cols].astype(str))
    X = hstack([cat, df[num_cols].values]).toarray()
    return X, ohe


def run(dataset: str):
    df, num_cols, cat_cols, y = (load_click_fraud() if dataset == "click_fraud" else load_churn())

    X_train_df, X_test_df, y_train, y_test = train_test_split(
        df, y, test_size=0.2, random_state=42, stratify=y
    )

    X_train, ohe = to_dense_matrix(X_train_df, num_cols, cat_cols, fit=True)
    X_test, _ = to_dense_matrix(X_test_df, num_cols, cat_cols, ohe=ohe)
    scaler = StandardScaler(with_mean=False)
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    results = {}

    # --- Bagging: Random Forest ---
    seeds_f1 = []
    for seed in range(5):
        single_tree = RandomForestClassifier(n_estimators=1, max_depth=None, random_state=seed)
        single_tree.fit(X_train, y_train)
        seeds_f1.append(f1_score(y_test, single_tree.predict(X_test)))
    rf = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    results["bagging_random_forest"] = {
        "single_tree_f1_mean": round(float(np.mean(seeds_f1)), 3),
        "single_tree_f1_std_across_seeds": round(float(np.std(seeds_f1)), 3),
        "forest_f1": round(f1_score(y_test, rf.predict(X_test)), 3),
    }

    # --- Boosting: LightGBM ---
    for c in cat_cols:
        X_train_df[c] = X_train_df[c].astype("category")
        X_test_df[c] = X_test_df[c].astype("category")
    train_set = lgb.Dataset(X_train_df[num_cols + cat_cols], label=y_train, categorical_feature=cat_cols)
    gbm = lgb.train(
        {"objective": "binary", "num_leaves": 31, "learning_rate": 0.05, "verbosity": -1},
        train_set, num_boost_round=400,
    )
    gbm_proba = gbm.predict(X_test_df[num_cols + cat_cols])
    results["boosting_lightgbm"] = {"f1": round(f1_score(y_test, gbm_proba >= 0.5), 3)}

    # --- Base learners for stacking/blending/voting ---
    logreg = LogisticRegression(max_iter=1000, class_weight="balanced")
    logreg.fit(X_train_s, y_train)
    logreg_proba_test = logreg.predict_proba(X_test_s)[:, 1]

    mlp = MLPClassifier(hidden_layer_sizes=(32,), max_iter=200, random_state=42)
    mlp.fit(X_train_s, y_train)
    mlp_proba_test = mlp.predict_proba(X_test_s)[:, 1]

    results["base_learners"] = {
        "logreg_f1": round(f1_score(y_test, logreg_proba_test >= 0.5), 3),
        "mlp_f1": round(f1_score(y_test, mlp_proba_test >= 0.5), 3),
        "lightgbm_f1": results["boosting_lightgbm"]["f1"],
    }

    # --- Stacking (k-fold out-of-fold, no leakage) ---
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof = np.zeros((len(X_train), 3))
    for train_idx, val_idx in kf.split(X_train):
        lr_fold = LogisticRegression(max_iter=1000).fit(X_train_s[train_idx], y_train[train_idx])
        oof[val_idx, 0] = lr_fold.predict_proba(X_train_s[val_idx])[:, 1]

        mlp_fold = MLPClassifier(hidden_layer_sizes=(32,), max_iter=200, random_state=42).fit(
            X_train_s[train_idx], y_train[train_idx]
        )
        oof[val_idx, 1] = mlp_fold.predict_proba(X_train_s[val_idx])[:, 1]

        gbm_fold_set = lgb.Dataset(
            X_train_df.iloc[train_idx][num_cols + cat_cols], label=y_train[train_idx],
            categorical_feature=cat_cols,
        )
        gbm_fold = lgb.train(
            {"objective": "binary", "num_leaves": 31, "learning_rate": 0.05, "verbosity": -1},
            gbm_fold_set, num_boost_round=200,
        )
        oof[val_idx, 2] = gbm_fold.predict(X_train_df.iloc[val_idx][num_cols + cat_cols])

    meta = LogisticRegression(max_iter=1000)
    meta.fit(oof, y_train)
    test_base_preds = np.column_stack([logreg_proba_test, mlp_proba_test, gbm_proba])
    stacked_proba = meta.predict_proba(test_base_preds)[:, 1]
    results["stacking"] = {"f1": round(f1_score(y_test, stacked_proba >= 0.5), 3)}

    # --- Voting (soft) ---
    soft_vote_proba = (logreg_proba_test + mlp_proba_test + gbm_proba) / 3
    results["voting_soft"] = {"f1": round(f1_score(y_test, soft_vote_proba >= 0.5), 3)}

    print(f"\n=== Ensemble comparison — {dataset} ===")
    for k, v in results.items():
        print(f"{k}: {v}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["click_fraud", "churn"], default="click_fraud")
    args = ap.parse_args()
    run(args.dataset)
