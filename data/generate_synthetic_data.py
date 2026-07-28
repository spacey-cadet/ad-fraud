"""
Synthetic data generator for the ad-supported subscription platform.

Why one generator for both services
------------------------------------
The two ML systems in this repo protect two different revenue streams of the
*same* product: an ad-supported media subscription app.

  - click_fraud     -> protects AD revenue (real-time, per-click decision)
  - churn_prediction -> protects SUBSCRIPTION revenue (batch, per-user/day decision)

Both models score the same underlying users and share a subset of behavioral
features (device fingerprint stability, session cadence, engagement quality).
That shared feature surface is exactly what lives in the feature store
(feature_repo/), so this script generates:

  1. users.parquet              - entity table (shared dimension)
  2. ad_clicks.parquet          - raw click events (streaming source)
  3. subscription_events.parquet- raw billing/usage events (batch source)
  4. dim_advertisers.parquet    - referential integrity target for dbt tests

Run:
    python data/generate_synthetic_data.py --out ./data/raw --n-users 20000
"""
import argparse
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)


def gen_users(n_users: int) -> pd.DataFrame:
    user_ids = np.arange(1, n_users + 1)
    # A small slice of users are bot-like (drives click-fraud) and a
    # correlated-but-not-identical slice are churn-prone (drives cancellations).
    is_bot = RNG.random(n_users) < 0.02
    is_churn_prone = (RNG.random(n_users) < 0.12) | (is_bot & (RNG.random(n_users) < 0.3))

    device_type = RNG.choice(
        ["mobile_ios", "mobile_android", "desktop_web", "smart_tv", "tablet"],
        size=n_users,
        p=[0.32, 0.33, 0.18, 0.12, 0.05],
    )
    signup_date = pd.to_datetime("2024-01-01") + pd.to_timedelta(
        RNG.integers(0, 900, size=n_users), unit="D"
    )

    return pd.DataFrame(
        {
            "user_id": user_ids,
            "device_type": device_type,
            "is_bot_ground_truth": is_bot,          # label source for click-fraud
            "is_churn_prone_ground_truth": is_churn_prone,  # label source for churn
            "signup_date": signup_date,
        }
    )


def gen_advertisers(n_advertisers: int = 400) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "advertiser_id": np.arange(1, n_advertisers + 1),
            "advertiser_name": [f"advertiser_{i}" for i in range(1, n_advertisers + 1)],
            "ad_network_id": RNG.integers(1, 25, size=n_advertisers),
            "is_active": RNG.random(n_advertisers) > 0.03,  # ~3% stale/inactive -> RI failures
        }
    )


def gen_ad_clicks(users: pd.DataFrame, advertisers: pd.DataFrame, n_events: int) -> pd.DataFrame:
    bot_users = users.loc[users.is_bot_ground_truth, "user_id"].to_numpy()
    human_users = users.loc[~users.is_bot_ground_truth, "user_id"].to_numpy()

    # Bots click far more per capita -> positive rate stays low (~2%) but
    # events skew heavily, matching the primer's "0.6%-2% positive rate" note.
    n_bot_events = int(n_events * 0.02)
    n_human_events = n_events - n_bot_events

    bot_ids = RNG.choice(bot_users, size=n_bot_events, replace=True)
    human_ids = RNG.choice(human_users, size=n_human_events, replace=True)

    user_id = np.concatenate([bot_ids, human_ids])
    is_fraud = np.concatenate([np.ones(n_bot_events), np.zeros(n_human_events)]).astype(bool)

    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    ts = [start + timedelta(seconds=int(s)) for s in RNG.integers(0, 30 * 24 * 3600, size=n_events)]

    advertiser_id = RNG.choice(advertisers["advertiser_id"], size=n_events)

    # Bots cluster on very few ad IDs and click faster in succession, but the
    # distributions deliberately overlap (some bots throttle themselves,
    # some humans burst-click during a sale) so a single-threshold heuristic
    # genuinely underperforms a learned model instead of solving the task by
    # construction.
    clicks_last_60s = np.where(
        is_fraud,
        RNG.poisson(7, size=n_events),
        RNG.poisson(2.0, size=n_events),
    )
    time_since_last_click_seconds = np.where(
        is_fraud,
        RNG.exponential(9, size=n_events),
        RNG.exponential(70, size=n_events),
    )

    df = pd.DataFrame(
        {
            "click_id": np.arange(1, n_events + 1),
            "user_id": user_id,
            "advertiser_id": advertiser_id,
            "event_ts": ts,
            "clicks_last_60s": clicks_last_60s,
            "time_since_last_click_seconds": time_since_last_click_seconds,
            "is_fraud": is_fraud,
        }
    ).sample(frac=1.0, random_state=42).reset_index(drop=True)

    # Label noise: ~4% of labels are flipped, standing in for the real-world
    # fact that ground-truth fraud labels themselves come from an imperfect
    # downstream review process, not an oracle.
    flip_idx = df.sample(frac=0.04, random_state=7).index
    df.loc[flip_idx, "is_fraud"] = ~df.loc[flip_idx, "is_fraud"]

    # Inject a small % of null click_ids to exercise the ingestion gate.
    null_idx = RNG.choice(df.index, size=int(len(df) * 0.001), replace=False)
    df.loc[null_idx, "click_id"] = np.nan
    return df


def gen_subscription_events(users: pd.DataFrame, as_of: str = "2026-07-01") -> pd.DataFrame:
    n = len(users)
    tenure_days = (pd.to_datetime(as_of) - users["signup_date"]).dt.days.clip(lower=1)
    churn_prone = users["is_churn_prone_ground_truth"].to_numpy()

    sessions_last_28d = np.where(
        churn_prone,
        RNG.poisson(3, size=n),
        RNG.poisson(16, size=n),
    )
    watch_minutes_last_28d = sessions_last_28d * RNG.normal(38, 10, size=n).clip(min=0)
    support_tickets_last_90d = np.where(
        churn_prone, RNG.poisson(0.9, size=n), RNG.poisson(0.1, size=n)
    )
    payment_failed_last_90d = np.where(
        churn_prone, RNG.random(n) < 0.22, RNG.random(n) < 0.02
    )

    # Cancellation labels lag a full billing cycle (~30d) — the primer's
    # "label-delay emphasis" for the batch/churn variant.
    will_cancel_next_cycle = churn_prone & (RNG.random(n) < 0.55)

    return pd.DataFrame(
        {
            "user_id": users["user_id"],
            "as_of_date": as_of,
            "tenure_days": tenure_days,
            "sessions_last_28d": sessions_last_28d,
            "watch_minutes_last_28d": watch_minutes_last_28d.round(1),
            "support_tickets_last_90d": support_tickets_last_90d,
            "payment_failed_last_90d": payment_failed_last_90d,
            "will_cancel_next_cycle": will_cancel_next_cycle,
        }
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="./data/raw")
    p.add_argument("--n-users", type=int, default=20000)
    p.add_argument("--n-clicks", type=int, default=300000)
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    users = gen_users(args.n_users)
    advertisers = gen_advertisers()
    clicks = gen_ad_clicks(users, advertisers, args.n_clicks)
    subs = gen_subscription_events(users)

    users.to_parquet(f"{args.out}/users.parquet", index=False)
    advertisers.to_parquet(f"{args.out}/dim_advertisers.parquet", index=False)
    clicks.to_parquet(f"{args.out}/ad_clicks.parquet", index=False)
    subs.to_parquet(f"{args.out}/subscription_events.parquet", index=False)

    print(f"users: {len(users):,} | clicks: {len(clicks):,} | sub rows: {len(subs):,}")
    print(f"click fraud positive rate: {clicks['is_fraud'].mean():.4%}")
    print(f"churn positive rate: {subs['will_cancel_next_cycle'].mean():.4%}")


if __name__ == "__main__":
    main()
