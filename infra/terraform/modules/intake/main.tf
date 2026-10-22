# The serverless intake: API Gateway (HTTP API) -> submit/status Lambdas -> S3, DynamoDB, SQS (+ dead-letter queue).
# The GPU worker that consumes the queue runs outside AWS; `aws_iam_policy.worker` is what its identity needs.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.69.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.8" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  functions = {
    submit = { route = "POST /v1/documents", timeout = 15, memory = 256 }
    status = { route = "GET /v1/documents/{id}", timeout = 5, memory = 128 }
  }
}

# --- storage -------------------------------------------------------------------------------------------------------

resource "aws_s3_bucket" "documents" {
  bucket        = "${var.name}-documents-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3 by default; set kms_key_arn for a customer-managed key (about $1 a month plus requests). Documents expire
# after job_ttl_days, so the default is an accepted exception to trivy's AVD-AWS-0132, not an oversight.
#trivy:ignore:AVD-AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == "" ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn == "" ? null : var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != ""
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    id     = "expire-documents"
    status = "Enabled"
    filter {}
    expiration { days = var.job_ttl_days }
    noncurrent_version_expiration { noncurrent_days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_dynamodb_table" "jobs" {
  name         = "${var.name}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.name}-jobs-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name}-jobs"
  visibility_timeout_seconds = var.worker_visibility_timeout_s
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = var.max_receive_count
  })
}

# --- functions -----------------------------------------------------------------------------------------------------

data "archive_file" "function" {
  for_each    = local.functions
  type        = "zip"
  source_dir  = "${var.lambda_dist}/${each.key}"
  output_path = "${path.root}/.build/${each.key}.zip"
}

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "function" {
  for_each           = local.functions
  name               = "${var.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

resource "aws_cloudwatch_log_group" "function" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.name}-${each.key}"
  retention_in_days = var.log_retention_days
}

# Least privilege, per function: submit writes one prefix, one table and one queue; status only reads the table.
data "aws_iam_policy_document" "submit" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/incoming/*"]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.jobs.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function["submit"].arn}:*"]
  }
}

data "aws_iam_policy_document" "status" {
  statement {
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function["status"].arn}:*"]
  }
}

resource "aws_iam_role_policy" "function" {
  for_each = local.functions
  name     = "${var.name}-${each.key}"
  role     = aws_iam_role.function[each.key].id
  policy   = each.key == "submit" ? data.aws_iam_policy_document.submit.json : data.aws_iam_policy_document.status.json
}

resource "aws_lambda_function" "function" {
  for_each         = local.functions
  function_name    = "${var.name}-${each.key}"
  role             = aws_iam_role.function[each.key].arn
  runtime          = "nodejs22.x"
  architectures    = ["arm64"]
  handler          = "index.handler"
  filename         = data.archive_file.function[each.key].output_path
  source_code_hash = data.archive_file.function[each.key].output_base64sha256
  timeout          = each.value.timeout
  memory_size      = each.value.memory

  environment {
    variables = {
      BUCKET         = aws_s3_bucket.documents.bucket
      TABLE          = aws_dynamodb_table.jobs.name
      QUEUE_URL      = aws_sqs_queue.jobs.url
      API_KEY_SHA256 = var.api_key_sha256
      MAX_BYTES      = tostring(var.max_bytes)
      JOB_TTL_DAYS   = tostring(var.job_ttl_days)
    }
  }

  tracing_config { mode = "Active" }
  depends_on = [aws_cloudwatch_log_group.function, aws_iam_role_policy.function]
}

# --- HTTP API ------------------------------------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "intake" {
  name          = "${var.name}-intake"
  protocol_type = "HTTP"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${var.name}-intake"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.intake.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle_rate
    throttling_burst_limit = var.throttle_burst
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId = "$context.requestId", route = "$context.routeKey", status = "$context.status",
      latencyMs = "$context.responseLatency", integrationMs = "$context.integrationLatency", ip = "$context.identity.sourceIp"
    })
  }
}

resource "aws_apigatewayv2_integration" "function" {
  for_each               = local.functions
  api_id                 = aws_apigatewayv2_api.intake.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.function[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "function" {
  for_each  = local.functions
  api_id    = aws_apigatewayv2_api.intake.id
  route_key = each.value.route
  target    = "integrations/${aws_apigatewayv2_integration.function[each.key].id}"
}

resource "aws_lambda_permission" "api" {
  for_each      = local.functions
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.function[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.intake.execution_arn}/*/*"
}

# --- the worker's permissions (attach to whatever identity runs it) -------------------------------------------------

data "aws_iam_policy_document" "worker" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.jobs.arn]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.documents.arn}/incoming/*"]
  }
  statement {
    actions   = ["dynamodb:UpdateItem", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
}

resource "aws_iam_policy" "worker" {
  name   = "${var.name}-worker"
  policy = data.aws_iam_policy_document.worker.json
}

# --- alarms (real AWS) ---------------------------------------------------------------------------------------------

locals {
  alarm_actions = var.alarm_topic_arn == "" ? [] : [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "dead_letters" {
  count               = var.alarms ? 1 : 0
  alarm_name          = "${var.name}-dead-letters"
  alarm_description   = "A job failed extraction max_receive_count times and sits in the dead-letter queue (docs/RUNBOOK.md#deadletters)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letter.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "queue_age" {
  count               = var.alarms ? 1 : 0
  alarm_name          = "${var.name}-queue-age"
  alarm_description   = "The oldest queued job has waited over 10 minutes: no worker is consuming (docs/RUNBOOK.md#queuebacklog)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.jobs.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 600
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "function_errors" {
  for_each            = var.alarms ? local.functions : {}
  alarm_name          = "${var.name}-${each.key}-errors"
  alarm_description   = "The ${each.key} function raised errors (docs/RUNBOOK.md#functionerrors)"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.function[each.key].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}
