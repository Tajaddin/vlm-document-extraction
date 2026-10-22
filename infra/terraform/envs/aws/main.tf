# The intake on a real AWS account. Validated, linted and scanned in CI; applying it needs the owner's account
# (docs/DEPLOY.md). Everything here fits the AWS free tier at demo volumes except API Gateway and CloudWatch alarms,
# which cost cents a month.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.69.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.8" }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "api_key_sha256" {
  description = "SHA-256 (hex) of the API key: printf %s \"$KEY\" | sha256sum"
  type        = string
}

variable "alarm_email" {
  description = "Where alarm notifications go; empty = no subscription"
  type        = string
  default     = ""
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "vlm-document-extraction", managed_by = "terraform" }
  }
}

resource "aws_sns_topic" "alarms" {
  name              = "vde-alarms"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

module "intake" {
  source          = "../../modules/intake"
  api_key_sha256  = var.api_key_sha256
  lambda_dist     = "${path.root}/../../../../lambdas/dist"
  alarms          = true
  alarm_topic_arn = aws_sns_topic.alarms.arn
}

output "api_url" {
  value = module.intake.api_endpoint
}

output "queue_url" {
  value = module.intake.queue_url
}

output "bucket" {
  value = module.intake.bucket
}

output "table" {
  value = module.intake.table
}

output "worker_policy_arn" {
  description = "Attach to the role or user the GPU worker runs as"
  value       = module.intake.worker_policy_arn
}
