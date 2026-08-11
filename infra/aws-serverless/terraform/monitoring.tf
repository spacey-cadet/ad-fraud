# --- Alerting: SNS topic + email subscription, CloudWatch alarms on
# errors, SQS backlog age, and DynamoDB throttling. Didn't exist in the
# repo before now — nothing here has been applied.
#
# Apply with:
#   terraform apply -var="alert_email=you@example.com"
# Then check your inbox — SNS sends a subscription-confirmation email
# that you must click before any alarm actually delivers. Until you
# click it, alarms will fire but you won't be notified.

variable "alert_email" {
  description = "Email address to receive CloudWatch alarm notifications"
  type        = string
}

resource "aws_sns_topic" "alerts" {
  name = "ad-platform-alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Lambda error alarms: one per function currently deployed. If you
# add more Lambdas later (there'll be a fourth once retraining/redeploy
# is automated), add a matching alarm here rather than assuming the
# dashboard alone will surface it. ---

resource "aws_cloudwatch_metric_alarm" "click_fraud_errors" {
  alarm_name          = "click-fraud-scoring-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 1
  metric_name          = "Errors"
  namespace            = "AWS/Lambda"
  period               = 300
  statistic            = "Sum"
  threshold            = 0
  alarm_description    = "click-fraud-scoring Lambda returned at least one error in the last 5 minutes"
  dimensions = {
    FunctionName = "click-fraud-scoring"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "churn_prediction_errors" {
  alarm_name          = "churn-prediction-scoring-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 1
  metric_name          = "Errors"
  namespace            = "AWS/Lambda"
  period               = 300
  statistic            = "Sum"
  threshold            = 0
  alarm_description    = "churn-prediction-scoring Lambda returned at least one error in the last 5 minutes"
  dimensions = {
    FunctionName = "churn-prediction-scoring"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "aggregator_errors" {
  alarm_name          = "click-windowing-aggregator-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 1
  metric_name          = "Errors"
  namespace            = "AWS/Lambda"
  period               = 300
  statistic            = "Sum"
  threshold            = 0
  alarm_description    = "click-windowing-aggregator Lambda returned at least one error in the last 5 minutes"
  dimensions = {
    FunctionName = "click-windowing-aggregator"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# --- SQS backlog age: catches the aggregator falling behind (or
# stopping entirely) even when it isn't throwing errors. A message
# sitting for 5+ minutes means the DynamoDB window data app.py reads is
# stale, which quietly degrades fraud scoring without any Lambda error
# ever firing. ---

resource "aws_cloudwatch_metric_alarm" "sqs_backlog_age" {
  alarm_name          = "ad-clicks-queue-backlog-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 2
  metric_name          = "ApproximateAgeOfOldestMessage"
  namespace            = "AWS/SQS"
  period               = 300
  statistic            = "Maximum"
  threshold            = 300 # 5 minutes
  alarm_description    = "Oldest message in ad-clicks-queue has been waiting over 5 minutes"
  dimensions = {
    QueueName = "ad-clicks-queue"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# --- DynamoDB throttling: on-demand billing mostly avoids this, but a
# sudden traffic spike (or a fraud burst, ironically) can still hit
# per-partition limits. ---

resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  alarm_name          = "click-windows-throttled-requests"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 1
  metric_name          = "ThrottledRequests"
  namespace            = "AWS/DynamoDB"
  period               = 300
  statistic            = "Sum"
  threshold            = 0
  alarm_description    = "click-windows table is throttling requests"
  dimensions = {
    TableName = "click-windows"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}
