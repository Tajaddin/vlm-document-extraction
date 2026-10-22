variable "name" {
  description = "Prefix for every resource name"
  type        = string
  default     = "vde"
}

variable "api_key_sha256" {
  description = "SHA-256 (hex) of the API key clients send as X-API-Key; the key itself never reaches AWS"
  type        = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.api_key_sha256))
    error_message = "api_key_sha256 must be 64 lower-case hex characters."
  }
}

variable "lambda_dist" {
  description = "Folder holding the built handlers (lambdas/dist): submit/index.mjs and status/index.mjs"
  type        = string
}

variable "max_bytes" {
  description = "Largest document the submit function accepts"
  type        = number
  default     = 4194304
}

variable "job_ttl_days" {
  description = "Days a job record and its image are kept"
  type        = number
  default     = 30
}

variable "max_receive_count" {
  description = "Deliveries of a job before SQS moves it to the dead-letter queue"
  type        = number
  default     = 3
}

variable "worker_visibility_timeout_s" {
  description = "How long a worker holds a job before SQS offers it again; longer than the slowest extraction"
  type        = number
  default     = 300
}

variable "throttle_rate" {
  description = "API Gateway steady-state requests per second"
  type        = number
  default     = 20
}

variable "throttle_burst" {
  description = "API Gateway burst"
  type        = number
  default     = 40
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "alarms" {
  description = "CloudWatch alarms on the dead-letter queue, queue age and function errors (real AWS only)"
  type        = bool
  default     = false
}

variable "alarm_topic_arn" {
  description = "SNS topic the alarms notify; empty = alarms with no action"
  type        = string
  default     = ""
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key for the document bucket; empty = SSE-S3 (AWS-managed keys)"
  type        = string
  default     = ""
}
