# Ad Platform ML — AWS Serverless (branch: aws-serverless)

This branch is a real, long-lived deployment target for the click-fraud and
churn-prediction scoring services — not a fork meant to diverge from `main`
forever. Shared training/model code is meant to stay identical across both
branches; only `infra/`-level deployment config differs. If you find
yourself editing `services/*/training/train.py` or the model logic itself
differently here than on `main`, that's a sign something should be merged
back rather than kept branch-specific.

For architecture reasoning, alternatives considered, and what was
deliberately lost in each swap below, see
[`docs/decisions/0001-local-vs-aws-serverless.md`](docs/decisions/0001-local-vs-aws-serverless.md).

---

## Departure from `main`

`main` runs a fully local, self-hostable stack via `docker-compose`:
Redpanda, Faust, Feast + Redis, MLflow, Prometheus, Grafana. Free to run
indefinitely, no cloud account required.

This branch replaces every piece of that stack with an AWS-native,
serverless-first equivalent, scoped to a **~$15/month budget across all
three ad-platform-ml projects combined** (this repo is Project 1 of 3):

| Local (`main`)              | AWS (`aws-serverless`)                     |
|------------------------------|---------------------------------------------|
| Redpanda + Faust (streaming) | SQS → aggregator Lambda → DynamoDB          |
| Redis (Feast online store)   | DynamoDB (`click-windows` table)            |
| Prometheus + Grafana         | CloudWatch metrics, alarms, dashboard       |
| MLflow                       | Stays local-only — not replicated in AWS    |
| Argo Rollouts                | CI-gated simulator only, no live rollout    |
| docker-compose (serving)     | Lambda container images + Function URLs     |

Deliberately **avoided**: ElastiCache, MSK, NAT Gateway, always-on Fargate.
None of these have a meaningful free tier, and any single one of them can
blow the entire cross-project budget on its own.

Nothing here is meant to make the local stack obsolete — `main` stays
useful for offline development and doesn't depend on an AWS account at all.

---

## What's actually running

Three Lambda functions (container image, `linux/amd64`), one Lambda
(zip-packaged, pure Python):

- **`click-fraud-scoring`** — LightGBM click-fraud model, public Function
  URL, reads live rolling click-count from DynamoDB at score time (see
  `clicks_last_60s_source` in the response — `"dynamodb"` means the real
  pipeline is being used; `"request_body"` means it fell back).
- **`churn-prediction-scoring`** — LightGBM churn model, public Function
  URL.
- **`click-ingest`** — validates incoming click events (Pydantic) and
  publishes them to SQS. This is the real production entry point for click
  events; `test_publish_click.py` is a debug-only stand-in that bypasses it.
- **`click-windowing-aggregator`** — zip-packaged, no Docker image. Consumes
  SQS in batches, computes a **fixed 60-second tumbling window** per user
  (coarser than the local stack's true sliding window — documented, not
  hidden), writes counts to DynamoDB with a TTL.

Supporting infra: an SQS queue + dead-letter queue, a DynamoDB table
(`click-windows`, on-demand billing), an SNS topic + email subscription for
alerts, CloudWatch alarms (Lambda errors, SQS backlog age, DynamoDB
throttling), a CloudWatch dashboard, and a GitHub OIDC role so CI can
deploy without long-lived AWS keys.

---

## Repo layout (this branch)

```
services/
├── click_fraud/{serving,training}/       # underscore — Python package convention
├── churn_prediction/{serving,training}/
└── click_ingest/serving/

infra/aws-serverless/
├── click-fraud/Dockerfile.lambda          # hyphen — matches infra/ convention
├── churn-prediction/Dockerfile.lambda
├── click-ingest/Dockerfile.lambda
├── lambda_src/aggregator/handler.py       # zip-packaged, no Dockerfile
├── test_publish_click.py                  # manual SQS debug tool, not a producer
└── terraform/
    ├── main.tf            # ECR repos, IAM, scoring Lambdas, dashboard
    ├── streaming.tf        # SQS, DynamoDB, aggregator Lambda
    ├── monitoring.tf       # SNS, CloudWatch alarms
    ├── ingest.tf            # click-ingest Lambda + scoped IAM role + alarm
    ├── github-oidc.tf       # GitHub Actions deploy role
    ├── variables.tf
    └── outputs.tf

.github/workflows/deploy-aws-serverless.yml   # builds+pushes on push to this branch
```

**Naming note:** `services/` uses underscores, `infra/aws-serverless/` uses
hyphens. Both are correct for their own directory — this has already caused
one Docker build failure from a mismatched `COPY` path, worth knowing before
adding a fourth service.

---

## Deploying

Full step-by-step commands (initial deploy, redeploy, auth, troubleshooting,
day-to-day operations) live in the command reference PDF generated
alongside this branch — not duplicated here to avoid the two going out of
sync. In short:

1. `terraform init && terraform apply -target=<ecr repos>` (bootstrap ECR
   first — Lambda needs an image to exist before it can reference one)
2. `docker buildx build --platform linux/amd64 --provenance=false
   --sbom=false ... --push` for each service (the two `--provenance`/`--sbom`
   flags are required — default Buildx output is rejected by Lambda)
3. `terraform apply` for everything else
4. Confirm the SNS email subscription
5. Set `AWS_DEPLOY_ROLE_ARN` as a GitHub secret from `terraform output
   github_deploy_role_arn`

**Redeploying after a code change is not automatic on save or push to
ECR** — a running Lambda stays pinned to the image digest it was deployed
with. Either push to this branch (GitHub Actions redeploys click-fraud and
churn-prediction automatically) or run `aws lambda update-function-code`
manually. `click-ingest` isn't in the CI build matrix yet — still manual.

---

## Known open items

- **`click-ingest` isn't in the GitHub Actions build matrix** —
  `deploy-aws-serverless.yml`'s `strategy.matrix.service` only lists
  `click-fraud` and `churn-prediction`. Redeploy it manually until added.
- **`user_id` typing is inconsistent** — `click-ingest` accepts it as a
  string; `click-fraud`'s request model types it as `int` and casts to
  `str()` before the DynamoDB lookup. Works today because of that cast;
  worth making consistent deliberately rather than relying on it.
- **No real production click-event source yet** — `click-ingest` is built
  and working, but nothing external actually calls it yet. Where real
  click events originate (ad-serving path, client-side beacon, etc.) is
  still an open design question.
- **Retraining → redeploy loop is unbuilt.** `train.py` writes
  `training_summary.json` (including `total_cost_usd` for a future
  cost-weighted quality gate), but nothing yet consumes it — no S3 request
  logging, no label-join job, no nightly retrain/gate/deploy automation.
- **Drift monitoring is unbuilt** — planned to ride on the same S3 request
  log as retraining (feature drift via PSI, rolling fraud-rate tracking,
  score-distribution tracking), not yet implemented.
- **Project 2 (churn escalation, XGBoost) and Project 3 (WAVLM speech
  emotion) haven't been started on this branch.**
