# --- IAM role that GitHub Actions assumes via OIDC, so the deploy
# workflow authenticates without a long-lived AWS access key sitting in
# a GitHub secret. Nothing here existed before now -- the workflow file
# referenced AWS_DEPLOY_ROLE_ARN but nothing ever created that role.
#
# IMPORTANT: replace spacey-cadet below with your actual GitHub username/
# org if this repo is ever forked or moved -- the trust policy's `sub`
# condition is scoped to this exact repo + branch on purpose, so a fork
# can't assume this role.

variable "github_org_repo" {
  description = "GitHub org/repo allowed to assume the deploy role, e.g. spacey-cadet/ad-fraud"
  type        = string
  default     = "spacey-cadet/ad-fraud"
}

# GitHub's OIDC provider -- one per AWS account, safe to create once and
# reuse across repos/roles. If this already exists in the account
# (created for a different repo previously), remove this resource and
# reference the existing provider by ARN instead, or `terraform import` it.
resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "github_deploy" {
  name = "ad-platform-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Restricts to pushes on the aws-serverless branch specifically,
          # not any branch or any PR in the repo.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org_repo}:ref:refs/heads/aws-serverless"
        }
      }
    }]
  })
}

# Scoped to exactly what the workflow does: push images to these two ECR
# repos, and update these two Lambda functions' code. Nothing broader --
# this role cannot touch Terraform state, IAM, or any other service.
resource "aws_iam_role_policy" "github_deploy_access" {
  name = "github-deploy-ecr-lambda-access"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = [
          aws_ecr_repository.click_fraud.arn,
          aws_ecr_repository.churn_prediction.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:UpdateFunctionCode"]
        Resource = [
          aws_lambda_function.click_fraud.arn,
          aws_lambda_function.churn_prediction.arn
        ]
      }
    ]
  })
}

output "github_deploy_role_arn" {
  value       = aws_iam_role.github_deploy.arn
  description = "Set this as the AWS_DEPLOY_ROLE_ARN secret in the GitHub repo settings"
}
