# Deploying to real accounts

Everything in this repository runs locally without an account. These are the steps that need one; each is the
owner's to take, and each costs money only where it says so.

## AWS (backlog #19)

The same Terraform module that runs on Floci. At demo volumes the Lambdas, S3, SQS and DynamoDB stay within the AWS
free tier; API Gateway HTTP APIs cost about $1 per million requests and the CloudWatch alarms about $0.10 each a
month after the first ten.

1. Create an AWS account and an IAM user or SSO role for Terraform; configure the AWS CLI with it.
2. Make an API key and keep it somewhere safe: `openssl rand -hex 24`. Terraform only ever sees its digest:
   ```bash
   export TF_VAR_api_key_sha256=$(printf %s "$KEY" | sha256sum | cut -d' ' -f1)
   ```
3. Build the functions and apply:
   ```bash
   cd lambdas && npm ci && npm run build && cd ..
   terraform -chdir=infra/terraform/envs/aws init
   terraform -chdir=infra/terraform/envs/aws apply -var alarm_email=you@example.com
   ```
4. Give the worker an identity: attach the `worker_policy_arn` output to an IAM role or user, and run the worker
   where the GPU is with that identity's credentials, `VDE_AWS_ENDPOINT_URL=` (empty: real AWS), and the
   `queue_url` and `bucket` outputs.
5. `terraform destroy` removes everything (the bucket is created with `force_destroy`).

## Vertex AI (backlog #18)

Gemini 2.5 Flash is listed at about $0.30 per million input tokens and $2.50 per million output; the 200 test
documents here are about 300,000 input tokens, a few cents.

1. A Google Cloud project with billing, and the Vertex AI API enabled.
2. `gcloud auth application-default login` (the SDK picks up these credentials).
3. Run it on both test sets:
   ```bash
   VDE_VERTEX_PROJECT=<project-id> uv run vde eval --dataset fatura --approach vertex
   VDE_VERTEX_PROJECT=<project-id> uv run vde eval --dataset cord --approach vertex
   ```
   (`--approach vertex` is wired into the CLI with the adapter; the run writes its report next to the local
   models' in `reports/eval/`.)
