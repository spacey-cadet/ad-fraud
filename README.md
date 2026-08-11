# Ad Platform ML

Two scoring services — click-fraud detection and churn prediction — sharing
a feature/user base. This is **Project 1 of 3** in a broader ad-platform-ml
effort (Project 2: churn escalation detector, XGBoost; Project 3: WAVLM
speech emotion recognition — neither started yet).

This repo has two live, intentionally different deployment targets on two
branches:

- **`main`** — a fully local, self-hostable stack. Free, no cloud account
  needed, good for offline development.
- **`aws-serverless`** — a real AWS deployment, serverless-first, scoped to
  a **~$15/month budget across all three projects combined**.

Both branches share the same training/model code
(`services/*/training/`, `services/*/serving/app.py`'s core scoring logic).
Only `infra/`-level deployment config differs between them. If you find
yourself editing model logic differently on one branch than the other,
that's a sign it should be merged back rather than kept branch-specific.

For the full reasoning behind every local→AWS swap below — alternatives
considered, what was deliberately lost in each one — see
[`docs/decisions/0001-local-vs-aws-serverless.md`](docs/decisions/0001-local-vs-aws-serverless.md).

---

## Which branch am I looking at?

| | `main` | `aws-serverless` |
|---|---|---|
| Streaming | Redpanda + Faust | SQS → aggregator Lambda → DynamoDB |
| Online feature store | Redis (via Feast) | DynamoDB (`click-windows` table) |
| Metrics/dashboards | Prometheus + Grafana | CloudWatch metrics, alarms, dashboard |
| Experiment tracking | MLflow | MLflow (local-only, not replicated in AWS) |
| Rollout strategy | Argo Rollouts | CI-gated simulator only, no live rollout |
| Serving | docker-compose | Lambda container images + Function URLs |
| Cost | Free | ~$15/month (shared across all 3 projects) |
| Requires | Docker | AWS account, Docker, Terraform |

Deliberately **avoided** on the AWS side: ElastiCache, MSK, NAT Gateway,
always-on Fargate. None have a meaningful free tier, and any one of them
alone can blow the entire cross-project budget.

Neither branch is meant to make the other obsolete — `main` stays useful
for fast local iteration without any cloud dependency; `aws-serverless` is
the real deployment target once something's ready to actually serve traffic.

---

## Local stack (`main`)

Run via `docker-compose`. See `PIPELINE_README.md` on this branch for the
full local setup, service ports (click-fraud: 8001, churn-prediction: 8002),
and `make up` / `make down` workflow.

```
services/
├── click_fraud/{serving,training,streaming}/
│   └── streaming/producer.py     # publishes synthetic clicks to Redpanda
└── churn_prediction/{serving,training}/
infra/k8s/                         # placeholder for future cluster manifests
```

---

## AWS stack (`aws-serverless`)

### What's running

Three Lambda functions (container image, `linux/amd64`), one Lambda
(zip-packaged, pure Python):

- **`click-fraud-scoring`** — LightGBM click-fraud model, public Function
  URL, reads live rolling click-count from DynamoDB at score time. Check
  the response's `clicks_last_60s_source` field — `"dynamodb"` means the
  real pipeline is being used; `"request_body"` means it fell back.
- **`churn-prediction-scoring`** — LightGBM churn model, public Function URL.
- **`click-ingest`** — validates incoming click events (Pydantic) and
  publishes them to SQS. This is the real production entry point for click
  events; `test_publish_click.py` is a debug-only stand-in that bypasses it.
- **`click-windowing-aggregator`** — zip-packaged, no Docker image. Consumes
  SQS in batches, computes a **fixed 60-second tumbling window** per user
  (coarser than `main`'s true sliding window — documented, not hidden),
  writes counts to DynamoDB with a TTL.

Supporting infra: SQS queue + dead-letter queue, DynamoDB table
(`click-windows`, on-demand billing), SNS topic + email subscription for
alerts, CloudWatch alarms (Lambda errors, SQS backlog age, DynamoDB
throttling), a CloudWatch dashboard, and a GitHub OIDC role so CI can
deploy without long-lived AWS keys.

### Repo layout (this branch only)

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
    ├── streaming.tf       # SQS, DynamoDB, aggregator Lambda
    ├── monitoring.tf      # SNS, CloudWatch alarms
    ├── ingest.tf          # click-ingest Lambda + scoped IAM role + alarm
    ├── github-oidc.tf     # GitHub Actions deploy role
    ├── variables.tf
    └── outputs.tf

.github/workflows/deploy-aws-serverless.yml   # builds+pushes on push to this branch
```

**Naming note:** `services/` uses underscores, `infra/aws-serverless/` uses
hyphens. Both are correct for their own directory — this has already caused
one Docker build failure from a mismatched `COPY` path, worth knowing before
adding a fourth service.

### Deploying

Full step-by-step commands (initial deploy, redeploy, auth, troubleshooting,
day-to-day operations) live in the command reference PDF kept alongside
this branch — not duplicated here to avoid the two going out of sync. In
short:

1. `terraform init && terraform apply -target=<ecr repos>` — bootstrap ECR
   first, Lambda needs an image to exist before it can reference one.
2. `docker buildx build --platform linux/amd64 --provenance=false
   --sbom=false ... --push` for each service. The `--provenance`/`--sbom`
   flags are required — default Buildx output is rejected by Lambda.
3. `terraform apply` for everything else.
4. Confirm the SNS email subscription.
5. Set `AWS_DEPLOY_ROLE_ARN` as a GitHub secret from
   `terraform output github_deploy_role_arn`.

**Redeploying after a code change is not automatic** — a running Lambda
stays pinned to the image digest it was deployed with. Either push to this
branch (GitHub Actions redeploys `click-fraud` and `churn-prediction`
automatically) or run `aws lambda update-function-code` manually.
`click-ingest` isn't in the CI build matrix yet — still manual.

### Known open items

- **`click-ingest` isn't in the GitHub Actions build matrix** —
  `deploy-aws-serverless.yml`'s `strategy.matrix.service` only lists
  `click-fraud` and `churn-prediction`. Redeploy it manually until added.
- **`user_id` typing is inconsistent** — `click-ingest` accepts it as a
  string; `click-fraud`'s request model types it as `int` and casts to
  `str()` before the DynamoDB lookup. Works today because of that cast;
  worth making consistent deliberately rather than relying on it.
- **No real production click-event source yet** — `click-ingest` is built
  and working, but nothing external actually calls it yet. Where real click
  events originate (ad-serving path, client-side beacon, etc.) is still an
  open design question.
- **Retraining → redeploy loop is unbuilt.** `train.py` writes
  `training_summary.json` (including `total_cost_usd` for a future
  cost-weighted quality gate), but nothing yet consumes it — no S3 request
  logging, no label-join job, no nightly retrain/gate/deploy automation.
- **Drift monitoring is unbuilt** — planned to ride on the same S3 request
  log as retraining (feature drift via PSI, rolling fraud-rate tracking,
  score-distribution tracking), not yet implemented.
- **Project 2 (churn escalation, XGBoost) and Project 3 (WAVLM speech
  emotion) haven't been started on this branch.**

---

## Contributing / working across branches

- Keep model and training logic identical across `main` and
  `aws-serverless` — divergence there is a bug, not a feature.
- `infra/`-level files are branch-specific by design and shouldn't be
  cross-ported.
- This README describes both branches from wherever it's checked out —
  paths under "AWS stack" only exist on `aws-serverless`; paths under
  "Local stack" only exist on `main`. If you're not sure which branch
  you're on: `git branch --show-current`.