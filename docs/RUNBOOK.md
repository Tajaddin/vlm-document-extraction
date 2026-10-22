# Runbook

One entry per alert (Prometheus, `observability/alert_rules.yml`) and per CloudWatch alarm (Terraform, AWS only).
Each says what it means, how to confirm it, and what to do. Commands assume the local stack (`docker compose`).

## WorkerDown

Prometheus cannot scrape the worker for 2 minutes; nothing is being extracted.

- Confirm: `docker compose --profile worker ps worker` and `docker compose logs --tail 100 worker`.
- A crash on start is usually configuration: `VDE_QUEUE_URL` or `VDE_BUCKET` empty (`make worker-up` sets both from
  Terraform's outputs).
- Restart: `make worker-up`. Queued jobs wait in SQS meanwhile; nothing is lost while their retention lasts (4 days).

## WorkerNotPolling

The process answers but has not asked SQS for work in 10 minutes: the loop is stuck, usually on a model call.

- Confirm: `vde_worker_last_poll_timestamp_seconds` on `:9108/metrics`; `ollama ps` on the host (is a model loaded,
  on the GPU?).
- Ollama hung or out of VRAM: restart Ollama, then the worker. The job in flight becomes visible again after the
  visibility timeout and is retried.

## QueueBacklog

Over 50 documents have waited for 15 minutes: arrivals outpace extraction.

- Confirm: `vde_worker_queue_messages{state="waiting"}`; on AWS the `vde-queue-age` alarm.
- Add a worker (any number can share the queue), or switch to a faster model (`VDE_VLM_MODEL=qwen3.5:4b` measured
  faster, with lower accuracy: see `reports/eval/SUMMARY.md`).

## ExtractionFailing

Over 10% of extractions failed or are being retried. Failed jobs reach the dead-letter queue after 3 deliveries.

- Confirm: `vde_worker_jobs_total` by outcome; worker logs, event `extraction_failed` with its `error`:
  `truncated` (answers hitting the 2,048-token cap), `invalid_json`, `ollama 500` (model failed to load).
- `truncated` on many documents points at a model change; `ollama ...` errors at the host.
- After the fix, redrive the dead-letter queue to the main queue (SQS `StartMessageMoveTask`, or move the messages
  with the AWS CLI) so those documents are extracted.

## ReviewRateHigh

Over half the extractions of one kind carry a review flag for an hour. On the test sets the flags fire on a known
share of documents (`reports/eval/`); far above that means new layouts, bad scans or a degraded model.

- Sample flagged jobs (`GET /v1/documents/{id}`, `review` field) and look at the images.
- New layouts: add few-shot examples of them (`VDE_FEW_SHOT`) and measure on a dev set before switching.

## ExtractionSlow

p95 extraction time above 30 s for 15 minutes (normal: a few seconds per document on an RTX 4060).

- `ollama ps`: a model partly on the CPU ("14%/86% CPU/GPU") means the GPU's memory is taken by something else.
- Many long answers (`completion_tokens` in the worker logs near 2,048) mean padding; see ExtractionFailing.

## DeadLetters (CloudWatch `vde-dead-letters`)

A job reached the dead-letter queue. Its record in DynamoDB says `failed` and why (`error`). Fix the cause (see
ExtractionFailing), then redrive the dead-letter queue.

## QueueAge (CloudWatch `vde-queue-age`)

The oldest queued job is over 10 minutes old: no worker is consuming. See WorkerDown and WorkerNotPolling.

## FunctionErrors (CloudWatch `vde-submit-errors`, `vde-status-errors`)

A Lambda raised instead of answering. Look at its log group (`/aws/lambda/vde-submit`); each request logs one JSON
line with its route, status and request id. A configuration error (missing `BUCKET`, `TABLE` or `API_KEY_SHA256`)
fails every request; an AWS throttle or outage fails some, and `submit` answers 503 so clients retry.
