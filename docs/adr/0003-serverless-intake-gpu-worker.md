# 0003. A serverless intake in front of a GPU worker, joined by SQS

Date: 2026-10-22. Status: accepted.

## Context

Documents arrive at unpredictable times from other systems; extraction needs a GPU and takes seconds. AWS Lambda
cannot run a vision-language model (no GPU, 10 GB memory, 15-minute limit), and a GPU instance waiting for traffic
costs money every hour it waits.

## Decision

1. **API Gateway (HTTP API) and two TypeScript Lambdas take the documents**: `submit` checks the API key (by its
   SHA-256, in constant time), the declared type against the file's own bytes, and the size; stores the image in S3;
   records the job in DynamoDB; and queues it in SQS. `status` reads the job back. They scale to zero and cost
   nothing idle.
2. **The job id is a hash of the kind and the bytes.** A retried or repeated upload is the same job: DynamoDB's
   conditional put is the lock, and only the request that creates the record queues the job. If queueing fails,
   the record is deleted so a retry can start over (no job stuck in `queued` without a message).
3. **Extraction runs in a worker next to the GPU**, long-polling SQS. Any number of workers can share the queue;
   SQS's visibility timeout gives each job to one of them.
4. **Failures use SQS's own machinery.** A failed extraction is not deleted: SQS offers it again and, after three
   deliveries, moves it to the dead-letter queue. The worker marks the job `failed` on the last delivery so the
   client sees why. A message that is not a job goes to the dead-letter queue the same way.
5. **Least privilege per function**: `submit` may write one S3 prefix, one table and one queue; `status` may only
   read the table; the worker's policy is a separate resource to attach to whatever identity runs it.
6. **Gemini on Vertex AI is a drop-in extractor** for when a managed model is wanted: same interface, same schema.
   It is not called without the owner's billing go-ahead.

## Consequences

- End-to-end latency is the queue wait plus the extraction; a client polls `status` (or a webhook could be added).
- The worker must be running for jobs to complete; `WorkerDown`, `WorkerNotPolling` and the CloudWatch queue-age
  alarm cover that.
- DynamoDB holds the result (well under its 400 KB item limit for one document's fields).
