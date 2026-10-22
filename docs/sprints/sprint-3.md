# Sprint 3 retro: serverless intake

Dates: 2026-10-22. Milestone: [Sprint 3 - Serverless intake](https://github.com/Tajaddin/vlm-document-extraction/milestone/3).

**Goal:** documents arrive through API Gateway and TypeScript Lambdas, queue in SQS, are extracted by a GPU worker
and read back, all from one Terraform module applied to the Floci emulator in CI. **Met.** This sprint ran before
Sprint 2 finished: Sprint 2's measurements needed the GPU, which was in use elsewhere for a while, so the serverless
work went first and Sprint 2's pull request follows this one.

## Delivered

| Issue | Points | Result |
|---|---|---|
| #11 Lambdas | 5 | `submit` (API key by digest, type sniffed from the bytes, size cap, content-hash ids, record removed if queueing fails) and `status`; 16 tests, 100% line coverage |
| #12 Terraform | 5 | one module, Floci and AWS environments; least privilege per function; CloudWatch alarms on AWS; tflint and trivy clean |
| #13 worker | 3 | SQS long-poll, review flags, results to DynamoDB, failures retried and dead-lettered; metrics, heartbeat |
| #14 end to end and k6 | 3 | a document through the emulated API comes back extracted, in CI; k6 at four rates |
| #15 alerts | 3 | pulled in from Sprint 4: six alert rules with eight promtool scenarios, a runbook |
| #16 Vertex AI | 2 | pulled in from Sprint 4: Gemini behind the same interface, tested offline, not run |

21 of 21 points done (16 planned, 5 pulled in from Sprint 4).

## Measured

- **Terraform on Floci:** 27 resources applied; CI applies them on every push.
- **End to end** (`tests/integration/test_e2e.py`): submit, duplicate submit (same job back), status `queued`,
  worker, status `done` with the result, and a 401 without the key.
- **k6 on the emulator** (`reports/load/intake-emulator.json`; one machine, i5-13600KF, Docker Desktop; each submit
  a new document, so every one takes the full write path):

  | Offered | Submit p50 | p95 | p99 |
  |---|---|---|---|
  | 5/s | 10.2 ms | 15.0 ms | 1,139 ms (the first Lambda cold starts) |
  | 10/s | 9.8 ms | 12.7 ms | 15.4 ms |
  | 20/s | 8.9 ms | 12.1 ms | 25.8 ms |
  | 40/s | 9.1 ms | 17.0 ms | 71.4 ms |

  4,503 submits, 4,503 duplicate submits answered with the same job, 4,503 status reads, 0 failed requests,
  1 dropped iteration. Emulator numbers: they show the code path's behaviour, not AWS capacity.

## What went well

- One Terraform module for the emulator and AWS: the emulator run exercises the same IAM, queues and routes that
  would deploy, and the AWS environment is validated and scanned in CI without an account.
- Content-hash job ids made the intake idempotent with nothing but a conditional put.

## What did not

- **The Floci health check never passed**: the image has neither curl nor wget, so `compose --wait` failed in CI;
  it now speaks HTTP over bash's `/dev/tcp`.
- **A secret-scan finding went to GitHub anyway**: the scan's output was piped into `tail`, which hid its failure
  exit code, and the push ran. The finding was a false positive (the SHA-256 of the test key "test-key"); the test
  config now computes it, the allowlist covers the old commit, and pushes now run only after the scan passes.
- gitleaks scans every branch's history in CI, so the allowlist had to be on `sprint-1` too before its CI passed.
- The worker's heartbeat file assumed Linux's `/tmp`; on Windows the integration tests failed until it used the
  platform's temp directory.
- trivy flagged the bucket for not using a customer-managed KMS key; that costs money on AWS, so it is opt-in and
  the default is a documented exception.

## Carried over

- Sprint 2's measurements and model card (its own pull request, next).
