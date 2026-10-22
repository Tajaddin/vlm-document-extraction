output "api_id" {
  value = aws_apigatewayv2_api.intake.id
}

output "api_endpoint" {
  description = "Invoke URL (on Floci: http://<api_id>.execute-api.localhost.floci.io:4566)"
  value       = aws_apigatewayv2_api.intake.api_endpoint
}

output "bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "table" {
  value = aws_dynamodb_table.jobs.name
}

output "queue_url" {
  value = aws_sqs_queue.jobs.url
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.dead_letter.url
}

output "worker_policy_arn" {
  value = aws_iam_policy.worker.arn
}
