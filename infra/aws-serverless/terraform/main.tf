terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# --- ECR: one repo per service. Apply just these two first
#     (terraform apply -target=aws_ecr_repository.click_fraud
#      -target=aws_ecr_repository.churn_prediction), then build+push
#     images, THEN run a full apply for the Lambda functions below. A
#     Lambda pointing at an image tag that doesn't exist yet fails to
#     create — this ordering isn't optional. ---

resource "aws_ecr_repository" "click_fraud" {
  name                 = "click-fraud-serving"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecr_repository" "churn_prediction" {
  name                 = "churn-prediction-serving"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

# --- IAM: shared basic execution role for both functions. All they need
# is permission to write their own CloudWatch Logs — nothing else, since
# neither service calls another AWS API at runtime. ---

resource "aws_iam_role" "lambda_exec" {
  name = "ad-platform-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "basic_exec" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- Lambda functions ---

resource "aws_lambda_function" "click_fraud" {
  function_name = "click-fraud-scoring"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.click_fraud.repository_url}:latest"

  memory_size = 1024
  timeout     = 30

  environment {
    variables = {
      DECISION_THRESHOLD = "0.42"
      MODEL_VERSION       = "v1"
    }
  }
}

resource "aws_lambda_function" "churn_prediction" {
  function_name = "churn-prediction-scoring"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.churn_prediction.repository_url}:latest"

  memory_size = 1024
  timeout     = 30
}

# --- Function URLs: public HTTPS endpoints, no API Gateway. auth_type
# NONE means anyone with the URL can call /score — fine for a demo, but
# don't put anything sensitive behind it. Switch to AWS_IAM auth if that
# ever matters. ---

resource "aws_lambda_function_url" "click_fraud" {
  function_name      = aws_lambda_function.click_fraud.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_function_url" "churn_prediction" {
  function_name      = aws_lambda_function.churn_prediction.function_name
  authorization_type = "NONE"
}

# --- CloudWatch dashboard: the free replacement for self-hosted
# Grafana, built from metrics Lambda already reports automatically. ---

resource "aws_cloudwatch_dashboard" "ad_platform" {
  dashboard_name = "ad-platform-ml"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Invocations"
          view   = "timeSeries"
          region = var.aws_region
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.click_fraud.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.churn_prediction.function_name]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Errors"
          view   = "timeSeries"
          region = var.aws_region
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.click_fraud.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.churn_prediction.function_name]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Duration (ms)"
          view   = "timeSeries"
          region = var.aws_region
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.click_fraud.function_name],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.churn_prediction.function_name]
          ]
        }
      }
    ]
  })
}
