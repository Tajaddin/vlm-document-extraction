# The intake on the Floci emulator (no account, no cost): `make infra-up` after `docker compose up -d floci`.
# The same module as envs/aws; only the provider differs.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.69.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.8" }
    random  = { source = "hashicorp/random", version = "~> 3.9" }
  }
}

variable "endpoint" {
  description = "Floci's address as seen from Terraform"
  type        = string
  default     = "http://localhost:4566"
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    apigatewayv2 = var.endpoint
    cloudwatch   = var.endpoint
    dynamodb     = var.endpoint
    iam          = var.endpoint
    lambda       = var.endpoint
    logs         = var.endpoint
    s3           = var.endpoint
    sqs          = var.endpoint
    sts          = var.endpoint
  }
}

# A fresh random key per emulator stack; clients read it with `terraform output -raw api_key`.
resource "random_password" "api_key" {
  length  = 40
  special = false
}

module "intake" {
  source         = "../../modules/intake"
  api_key_sha256 = sha256(random_password.api_key.result)
  lambda_dist    = "${path.root}/../../../../lambdas/dist"
  # the local worker uses the fake or a local model; a job is offered again after two minutes
  worker_visibility_timeout_s = 120
}

output "api_key" {
  value     = random_password.api_key.result
  sensitive = true
}

output "api_id" {
  value = module.intake.api_id
}

output "api_url" {
  description = "Floci serves HTTP APIs on its execute-api domain"
  value       = "http://${module.intake.api_id}.execute-api.localhost.floci.io:4566"
}

output "bucket" {
  value = module.intake.bucket
}

output "table" {
  value = module.intake.table
}

output "queue_url" {
  value = module.intake.queue_url
}

output "dead_letter_queue_url" {
  value = module.intake.dead_letter_queue_url
}
