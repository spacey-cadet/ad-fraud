# --- Click ingestion endpoint: a third Lambda, separate from the two
# scoring functions in main.tf. Publishes validated click events to the
# ad-clicks-queue SQS queue (declared in streaming.tf) -- this is what
# replaces test_publish_click.py as the real way events get into the
# pipeline. Apply this alongside streaming.tf; it references
# aws_sqs_queue.ad_clicks from that file, same module.

resource "aws_ecr_repository" "click_ingest" {
  name                 = "click-ingest"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

# --- Deliberately its own role, not shared with the scoring Lambdas'
# lambda_exec role (main.tf). Scoring functions never need to touch SQS;
# this one needs exactly sqs:SendMessage and nothing else. Keeping them
# separate means a bug or compromise in one function can't reach
# permissions it was never meant to have. ---

resource "aws_iam_role" "click_ingest_exec" {
  name = "ad-platform-click-ingest-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "click_ingest_basic_exec" {
  role       = aws_iam_role.click_ingest_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "click_ingest_sqs_send" {
  name = "click-ingest-sqs-send-only"
  role = aws_iam_role.click_ingest_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.ad_clicks.arn
    }]
  })
}

resource "aws_lambda_function" "click_ingest" {
  function_name = "click-ingest"
  role          = aws_iam_role.click_ingest_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.click_ingest.repository_url}:latest"

  memory_size = 256 # no ML deps to load, this can stay small
  timeout     = 10

  environment {
    variables = {
      QUEUE_URL = aws_sqs_queue.ad_clicks.url
    }
  }
}

# --- Public Function URL, same auth posture as the two scoring
# endpoints (authorization_type = NONE). Anyone with the URL can queue a
# click event -- fine for now per the existing pattern, but this is a
# real production ingestion path, not a demo endpoint like scoring was
# originally described as. Worth revisiting auth here specifically if
# this goes further than internal testing. ---

resource "aws_lambda_function_url" "click_ingest" {
  function_name      = aws_lambda_function.click_ingest.function_name
  authorization_type = "NONE"
}

resource "aws_cloudwatch_metric_alarm" "click_ingest_errors" {
  alarm_name          = "click-ingest-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 1
  metric_name          = "Errors"
  namespace            = "AWS/Lambda"
  period               = 300
  statistic            = "Sum"
  threshold            = 0
  alarm_description    = "click-ingest Lambda returned at least one error in the last 5 minutes"
  dimensions = {
    FunctionName = "click-ingest"
  }
  alarm_actions = [aws_sns_topic.alerts.arn] # from monitoring.tf, same module
}

output "click_ingest_url" {
  value = "${aws_lambda_function_url.click_ingest.function_url}ingest"
}
