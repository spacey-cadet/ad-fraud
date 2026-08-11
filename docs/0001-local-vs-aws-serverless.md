# ADR 0001: Local Kafka-native stack vs. AWS serverless deployment target

## Status
Accepted — implemented on the `aws-serverless` branch, `main` keeps the local stack.

## Context
The local `docker-compose` stack (Redpanda, Faust, Feast+Redis, MLflow,
Prometheus, Grafana) is free and self-hostable, but every piece of it
assumes a long-running process. AWS's genuinely-free tier (Lambda's
1M requests + 400k GB-seconds/month, SQS/DynamoDB's perpetual free
tiers) is built around the opposite assumption: stateless, ephemeral,
pay-per-invocation compute. Deploying "the same architecture" to AWS
without acknowledging that mismatch means either an accidental bill
(ElastiCache, MSK, and always-on Fargate all cost real money from the
first minute) or a deployment that silently drops guarantees the local
version had. This ADR records which swaps were made, and what was
actually given up in each one — not just which vendor changed.

## Decisions

### Event bus + streaming aggregation: Redpanda/Faust → SQS/DynamoDB
**What's lost:** Kafka/Redpanda is a durable, replayable, ordered log;
Faust keeps a genuine sliding-window aggregation in its own state store.
SQS is at-least-once delivery with **no ordering guarantee and no
replay** — once a message is processed it's gone. The DynamoDB-backed
aggregator (`infra/aws-serverless/streaming/aggregator/handler.py`)
approximates Faust's window with a **fixed tumbling bucket**
(`floor(timestamp / 60) * 60`) rather than a true sliding window — a
click at the first second of a bucket and one at the last second both
count as "the same window," which is a coarser guarantee than what
Faust computes locally. This is a real behavioral difference, not
just an implementation detail, and should be named as such if this
repo comes up in an interview.

**What's kept:** the shape of the pattern — event arrives, gets
aggregated into a windowed count keyed by `user_id`, aggregate is
available for scoring to consume. That's the reviewable part of the
design; the exact windowing algorithm underneath is what changed.

**Open item:** `click_fraud/serving/app.py` currently takes
`clicks_last_60s` directly from the request body — it does not yet
read the DynamoDB-aggregated value this pipeline produces. Wiring
scoring to read from DynamoDB by `user_id` is the natural next step
if this needs to be end-to-end, not just "the aggregator runs."

### Online feature store: Redis → DynamoDB
Feast supports DynamoDB as an online store backend natively, so this
is a config-level swap, not an architectural one. Chosen specifically
because ElastiCache (managed Redis) has no perpetual free tier —
cheapest node runs ~$12+/month just for existing — while DynamoDB's
on-demand free tier (25GB, generous request allowance) never expires.

### Monitoring: Prometheus/Grafana → CloudWatch
Prometheus needs a continuously-running process to scrape; Lambda has
no such process, so there's nothing to scrape even if Prometheus were
deployed. CloudWatch gets invocation count, duration, error rate, and
throttles automatically, at zero cost, with zero code change — this
covers most of what Prometheus was providing operationally, without
custom instrumentation. Grafana was dropped rather than pointed at
CloudWatch as a data source, since CloudWatch Dashboards (3 free)
cover the same need without a second tool to maintain.

### Experiment tracking: MLflow stays local-only
Inference was already decoupled from MLflow before this branch existed
— both serving apps load `model.txt` directly with
`lgb.Booster(model_file=...)`, no MLflow client call at request time.
There's no reason to pay for a hosted tracking server when nothing in
the serving path needs one; MLflow stays a local/CI-time tool for
training and experiment comparison only.

### Progressive delivery: Argo Rollouts → not deployed
Real canary traffic-shifting needs an actual Kubernetes cluster —
not achievable on Lambda at any reasonable cost. The
`analysis_run_simulator.py` script remains the honest substitute:
it runs the same AnalysisRun decision logic in CI, without a live
cluster to execute the traffic shift against.

## Consequences
- At portfolio/demo traffic volumes, the AWS serverless target costs
  effectively $0/month: Lambda, DynamoDB, SQS, and CloudWatch (at this
  scale) are all within their perpetual free tiers. ECR image storage
  is the only line item likely to show up at all, and only past the
  first 500MB/12-month allowance.
- This budget holds at **toy/demo traffic only**. Lambda, DynamoDB, and
  S3 costs scale roughly linearly with real usage — "minimal cost" here
  means "minimal cost at portfolio scale," not "minimal cost at any
  scale." Worth stating explicitly rather than implying this is a
  production cost model.
- The local `docker-compose` stack remains the source of truth for
  "what would this look like with unlimited infrastructure budget";
  the AWS branch is a deliberately constrained, honestly-documented
  alternative — not a strictly-better replacement.
