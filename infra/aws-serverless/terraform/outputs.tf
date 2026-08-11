output "click_fraud_ecr_repo_url" {
  value = aws_ecr_repository.click_fraud.repository_url
}

output "churn_prediction_ecr_repo_url" {
  value = aws_ecr_repository.churn_prediction.repository_url
}

output "click_fraud_score_url" {
  value = "${aws_lambda_function_url.click_fraud.function_url}score"
}

output "churn_prediction_score_url" {
  value = "${aws_lambda_function_url.churn_prediction.function_url}score"
}

output "dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.ad_platform.dashboard_name}"
}
