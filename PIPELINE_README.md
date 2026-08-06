# Ad Platform ML: Click-Fraud Detection + Subscription-Churn Prediction

Two production-shaped ML services for the same product — an ad-supported
media subscription app — sharing one user base, one feature store pattern,
and one ensemble-methods discipline, built entirely on free / self-hostable
tools.

- **`services/click_fraud/`** — real-time scoring that protects **ad
  revenue** (per-click decision, streaming features, low-latency canary
  rollout).
- **`services/churn_prediction/`** — batch scoring that protects
  **subscription revenue** (per-user/day decision, dbt-built nightly mart,
  label lag of a full billing cycle).

They're not two unrelated demos bolted together: both score the same
`user_id` entity, both read from the shared `user_behavior` feature view,
and both are trained with the same baseline-hierarchy discipline
(heuristic → linear → tree ensemble → cost-aware threshold), which is made
explicit and runnable in `shared_ensemble/compare_ensembles.py`.

## Why this repo exists

This started from a set of interview-prep notes describing a fraud/churn ML
system design at a conceptual level, using several paid/managed tools
(Vertex AI Feature Store, Argo Rollouts on a managed cluster, etc.) as
illustrative names. This repo is the concrete, runnable version — every tool
below is free and self-hostable, and every metric in the code is computed
from real (synthetic) data, not asserted.

| Concept | Paid/managed original | Free equivalent used here |
|---|---|---|
| Feature store | Vertex AI Feature Store | **Feast** (OSS) + **Redis** (online store) |
| Stream processing | Apache Flink (managed) | **Faust** (pure-Python, Kafka-native) — Flink itself is free too, Faust just keeps this repo dependency-light |
| Event bus | Managed Kafka | **Redpanda** (Kafka-API-compatible, single binary) |
| Progressive delivery | Argo Rollouts (managed cluster) | **Argo Rollouts** (itself OSS) — manifests included, plus a runnable `analysis_run_simulator.py` for portfolio use without a live cluster |
| Data quality / drift | Evidently / Great Expectations | **whylogs** + **dbt tests** (all OSS) |
| Batch transforms | dbt on a paid warehouse | **dbt-core + DuckDB** (zero-infra, free) |
| Experiment tracking / registry | Managed MLflow / SageMaker | **MLflow** (self-hosted, OSS) |
| Orchestration | Managed Airflow | **GitHub Actions scheduled workflow** (free for public repos) — swap for Airflow/Prefect if you outgrow this |
| Monitoring | Datadog / managed Grafana | **Prometheus + Grafana** (self-hosted) |
| Model | LightGBM | unchanged — LightGBM is free either way |

Nothing here requires a cloud account or a credit card to run locally.

## Architecture

```
                    ┌──────────────────────────┐
                    │   users.parquet (shared)  │
                    │  bot-prone / churn-prone   │
                    └─────────────┬─────────────┘
                                  │
                 ┌────────────────┴────────────────┐
                 │                                  │
        ad_clicks (streaming)              subscription_events (batch)
                 │                                  │
        Redpanda → Faust windowed             dbt (DuckDB): staging →
        aggregation (Gate 1: null                churn_features mart
        completeness check)                    (Gate 2: referential
                 │                              integrity + completeness)
        Feast online store (Redis)                     │
                 │                              Feast offline store
        LightGBM scoring (FastAPI)                      │
                 │                              LightGBM scoring (FastAPI,
        Argo Rollouts canary                    batch-oriented, no
        (95/5, AnalysisRun on                   latency SLA)
        error-rate)                                     │
                 │                              GitHub Actions nightly
        Prometheus + Grafana ◄───────────────── retrain + dbt test
```

## Repo layout

```
data/generate_synthetic_data.py   # shared synthetic user base + both raw datasets
feature_repo/                     # Feast: entities, feature views, feature_store.yaml
services/
  click_fraud/
    streaming/                    # Redpanda producer + Faust windowed aggregation
    training/train.py             # baseline hierarchy + cost-matrix thresholding
    serving/                      # FastAPI + Dockerfile
    rollout/                      # Argo Rollouts manifest + analysis-run simulator
    tests/
  churn_prediction/
    dbt/                          # dbt-duckdb project: staging, marts, tests
    training/train.py             # baseline hierarchy on the dbt-built mart
    serving/                      # FastAPI + Dockerfile
    tests/
shared_ensemble/compare_ensembles.py  # bagging/boosting/stacking/blending/voting, both datasets
monitoring/                       # Prometheus config + Grafana dashboard/provisioning
infra/k8s/                        # placeholder for cluster manifests beyond rollout/
.github/workflows/
  ci.yml                          # lint, dbt build+test, unit tests, docker build
  nightly-churn-batch.yml         # scheduled batch retrain (Airflow-free orchestration)
```

## Running it

### 1. Generate data and build the warehouse
```bash
pip install -r requirements.txt
make data          # synthetic users, ad_clicks, subscription_events, dim_advertisers
make warehouse      # loads raw parquet into DuckDB, runs dbt, runs dbt tests
```

### 2. Train both models
```bash
make train-fraud    # baseline hierarchy + cost-matrix threshold, logged to MLflow
make train-churn     # same discipline, batch mart as input
```

### 3. Compare ensemble methods on both datasets
```bash
make ensembles-fraud
make ensembles-churn
```

### 4. Run the full stack (Redpanda, Redis, MLflow, Prometheus, Grafana, both APIs)
```bash
make up
# click-fraud scoring:  http://localhost:8001/score
# churn scoring:        http://localhost:8002/score
# MLflow:               http://localhost:5000
# Grafana:               http://localhost:3000 (admin/admin)
```

### 5. Tests
```bash
make test
```

## Design notes worth knowing before you present this

- **Cost-matrix thresholding, not Youden's J.** Click-fraud false positives
  (blocking a legitimate click) are an immediate, dollar-denominated cost;
  false negatives (paying out for fraud) are only discovered at end-of-month
  reconciliation. That asymmetry is why `train.py` sweeps thresholds against
  a real cost function instead of optimizing a symmetric statistic.
- **Ingestion gates live where the compute lives.** For the streaming
  service, the null-completeness check runs inside the Faust windowed
  aggregation itself (a stream side-output), not a separate batch suite —
  because ingestion is streaming, not landing-zone batch. For churn, the
  same 0%-null-tolerance rule is re-enforced as a dbt `not_null` test on the
  batch mart.
- **Referential integrity, not just null checks.** `stg_ad_clicks.sql`
  filters and dbt-tests `advertiser_id` against `dim_advertisers` — a stale
  advertiser record silently misattributes fraud cost to the wrong account,
  which is a worse failure mode than an obvious null.
- **Calibration direction isn't assumed.** The churn model's LightGBM F1 at
  the default 0.5 cutoff is *worse* than plain logistic regression despite a
  much higher AUC — that's a real, reproducible illustration of why you
  don't ship a model at its default threshold without checking calibration
  first, not a scripted example.
- **Stacking uses genuine out-of-fold predictions.** `compare_ensembles.py`
  builds the meta-learner's training data via k-fold CV specifically to
  avoid the leakage bug where a meta-learner sees inflated, overfit
  confidence from its own base models.

## Known simplifications 

- Synthetic data, not real traffic — the point is a correct, runnable
  pipeline shape, not real-world model performance.
- The Argo Rollouts manifest is real and valid but needs an actual
  Kubernetes cluster to execute; `analysis_run_simulator.py` is included so
  the canary-analysis *logic* is runnable without one.
- GitHub Actions' cron trigger stands in for a dedicated orchestrator
  (Airflow/Prefect); fine at this scale, worth naming as a scaling
  limitation if asked.