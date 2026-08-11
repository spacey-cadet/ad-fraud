# --- Real-time click-count windowing: SQS -> aggregator Lambda -> DynamoDB.
#
# This is what services/click_fraud/serving/app.py reads at score time
# (GetItem by user_id + window_start) instead of trusting the caller's
# self-reported clicks_last_60s. Nothing here is applied yet — this file
# didn't exist in the repo before now.
#
# Apply order: this needs its own `terraform init` first (new `archive`
# provider, declared below), then a normal `terraform apply`. It has no
# dependency on main.tf's resources, so it can be applied independently.

# --- DynamoDB: one item per (user_id, window_start). On-demand billing
# because click volume is bursty and unpredictable at this stage — paying
# per-request beats guessing a provisioned throughput number and either
# overpaying or getting throttled. TTL cleans up old windows automatically
# so the table doesn't grow forever. ---

resource "aws_dynamodb_table" "click_windows" {
  name         = "click-windows"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "window_start"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "window_start"
    type = "N"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# --- SQS: the queue click events land in before aggregation. Standard
# (not FIFO) — exact ordering within a window doesn't matter, only the
# count does. A dead-letter queue catches messages the aggregator fails
# to process after 3 tries, so a bad message can't silently vanish or
# block the queue forever. ---

resource "aws_sqs_queue" "ad_clicks_dlq" {
  name                      = "ad-clicks-queue-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "ad_clicks" {
  name                       = "ad-clicks-queue"
  visibility_timeout_seconds = 90 # >= 6x the aggregator's timeout, per AWS guidance

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ad_clicks_dlq.arn
    maxReceiveCount      = 3
  })
}

# --- Aggregator Lambda: pure Python/boto3, zip-packaged (no Docker image
# needed — this one's small and dependency-free, unlike the two scoring
# services). Source lives at infra/aws-serverless/lambda_src/aggregator/. ---

data "archive_file" "aggregator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_src/aggregator"
  output_path = "${path.module}/aggregator.zip"
}

resource "aws_iam_role" "aggregator_exec" {
  name = "ad-platform-aggregator-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "aggregator_basic_exec" {
  role       = aws_iam_role.aggregator_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Scoped narrowly: this role can only read SQS and write to this one
# DynamoDB table. It has no access to the ECR repos, the scoring
# Lambdas, or anything else in the account.
resource "aws_iam_role_policy" "aggregator_access" {
  name = "aggregator-sqs-dynamodb-access"
  role = aws_iam_role.aggregator_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.ad_clicks.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.click_windows.arn
      }
    ]
  })
}

resource "aws_lambda_function" "aggregator" {
  function_name = "click-windowing-aggregator"
  role          = aws_iam_role.aggregator_exec.arn
  runtime       = "python3.12"
  handler       = "handler.handler"
  filename      = data.archive_file.aggregator_zip.output_path
  source_code_hash = data.archive_file.aggregator_zip.output_base64sha256

  memory_size = 128
  timeout     = 15

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.click_windows.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "sqs_to_aggregator" {
  event_source_arn = aws_sqs_queue.ad_clicks.arn
  function_name    = aws_lambda_function.aggregator.arn
  batch_size       = 10
}
