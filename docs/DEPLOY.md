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

**Done 2026-10-23** on a free-trial project (reports in `reports/eval/*/vertex-gemini-3.8-flash-*`). Gemini 2.5
Flash, the model first planned, answered 404 for a new project in both `us-central1` and `global`; the 3.x Flash
models answer on the `global` endpoint, so the defaults are now `gemini-3.8-flash` and `global`. Measured usage:
1,602 input and 114 output tokens per invoice, 2,132 and 179 per receipt; at $0.75 / $3.75 per million (October
2026) the 200 test documents cost about $0.39.

1. A Google Cloud project with billing, and the Vertex AI API enabled
   (`gcloud services enable aiplatform.googleapis.com`).
2. `gcloud auth application-default login` (the SDK picks up these credentials).
3. Run it on both test sets (try `--split dev --limit 2` first; it costs a fraction of a cent):
   ```bash
   VDE_VERTEX_PROJECT=<project-id> uv run --extra vertex vde eval --dataset fatura --approach vertex
   VDE_VERTEX_PROJECT=<project-id> uv run --extra vertex vde eval --dataset cord --approach vertex
   ```
   (`--approach vertex` is wired into the CLI with the adapter; the run writes its report next to the local
   models' in `reports/eval/`. `VDE_VERTEX_MODEL` and `VDE_VERTEX_LOCATION` override the defaults.)
