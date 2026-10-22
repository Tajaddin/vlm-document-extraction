# 0004. Floci, not LocalStack, for AWS locally and in CI

Date: 2026-10-22. Status: accepted.

## Context

The intake has to be deployed and tested without an AWS account. LocalStack was the usual answer, but since
2026-03-23 its community image needs an account and an auth token
([testcontainers-java#11568](https://github.com/testcontainers/testcontainers-java/issues/11568)), which this
project cannot assume.

## Decision

Use **Floci** ([floci-io/floci](https://github.com/floci-io/floci), MIT, image `floci/floci:2.3.0`): no account or
token, runs Lambda functions in real AWS runtime containers, and serves API Gateway v2, S3, SQS and DynamoDB on one
port. The **same Terraform module** is applied to it (envs/floci) as would be applied to AWS (envs/aws); only the
provider's endpoints differ. CI applies it, runs the worker and an end-to-end test against it, and runs k6 against
its API Gateway.

Two Floci details the code handles: it injects `AWS_ENDPOINT_URL` into function containers (the AWS SDK picks it
up; S3 then needs path-style addressing), and it serves HTTP APIs on `<api id>.execute-api.localhost.floci.io`,
routing by host, so a client inside the Docker network sends that `Host` header to `floci:4566`.

## Consequences

- Timings measured on Floci describe the code path on one machine, not AWS: every load report says so.
- IAM policies are applied but not enforced by default on Floci; their correctness is checked by trivy, tflint and
  review, and would only be proven on AWS (backlog #19).
- Floci is young (release 2.3.0, 2026-10-15); its version is pinned in docker-compose.yml and CI.
