// POST /v1/documents?kind=invoice|receipt with the image as the body.
//
// The job id is a hash of the kind and the bytes, so a client that retries (or sends the same document twice) gets the
// same job back instead of paying for a second extraction. DynamoDB's conditional put is the lock: only the request
// that creates the record queues the job, and it marks the record `sentAt` once the message is in the queue. If
// queueing fails, the record is removed again so a retry can start over. Two existing records are queued again instead
// of returned: a failed job (at most MAX_REQUEUES times), and one still "queued" without `sentAt` REQUEUE_AFTER_SECONDS
// after it was written, which is what a function stopped between the put and the send leaves behind. Taking a record
// over is a put conditional on it being unchanged since it was read, so concurrent retries still queue it once.

import { PutObjectCommand } from "@aws-sdk/client-s3";
import { SendMessageCommand } from "@aws-sdk/client-sqs";
import { ConditionalCheckFailedException } from "@aws-sdk/client-dynamodb";
import { DeleteCommand, GetCommand, PutCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";
import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";
import { createHash } from "node:crypto";

import { dynamo, s3, sqs } from "./lib/clients.js";
import { loadConfig } from "./lib/config.js";
import { authorized, header, json, logRequest, problem } from "./lib/http.js";
import { EXTENSIONS, isImageType, pixels, sniff } from "./lib/image.js";
import { isKind, view, type Job } from "./lib/jobs.js";

const config = loadConfig();

export async function handler(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  const started = Date.now();
  const response = await submit(event);
  logRequest({ route: "submit", requestId: event.requestContext.requestId, status: response.statusCode, ms: Date.now() - started });
  return response;
}

async function submit(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  if (!authorized(event, config.apiKeySha256)) return problem(401, "missing or wrong X-API-Key");

  const kind = event.queryStringParameters?.kind ?? "invoice";
  if (!isKind(kind)) return problem(400, "kind must be invoice or receipt");

  const contentType = (header(event, "content-type") ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
  if (!isImageType(contentType)) return problem(415, "send image/jpeg or image/png");
  if (!event.body) return problem(400, "empty body");

  const bytes = Buffer.from(event.body, event.isBase64Encoded ? "base64" : "binary");
  if (bytes.length > config.maxBytes) return problem(413, `larger than ${String(config.maxBytes)} bytes`);
  if (sniff(bytes) !== contentType) return problem(415, `the bytes are not ${contentType}`);
  const size = pixels(bytes, contentType);
  if (size === undefined) return problem(415, `the ${contentType} header does not give the image's size`);
  if (size > config.maxPixels) return problem(413, `larger than ${String(config.maxPixels)} pixels`);

  const id = createHash("sha256").update(kind).update(":").update(bytes).digest("hex").slice(0, 32);
  const key = `incoming/${id}.${EXTENSIONS[contentType]}`;
  const now = new Date();
  const job: Job = {
    id,
    kind,
    status: "queued",
    key,
    contentType,
    bytes: bytes.length,
    createdAt: now.toISOString(),
    updatedAt: now.toISOString(),
    expiresAt: Math.floor(now.getTime() / 1000) + config.jobTtlDays * 86400,
  };

  const location = { location: `/v1/documents/${id}` };
  if (!(await claim(job))) {
    const seen = await read(id);
    if (!seen || !retryable(seen, now)) return duplicate(seen, location);
    job.requeues = (seen.requeues ?? 0) + 1;
    if (!(await claim(job, seen))) return duplicate(await read(id), location); // another request took it over first
  }

  try {
    await s3.send(new PutObjectCommand({ Bucket: config.bucket, Key: key, Body: bytes, ContentType: contentType }));
    await sqs.send(new SendMessageCommand({ QueueUrl: config.queueUrl, MessageBody: JSON.stringify({ id, kind, key }) }));
  } catch (e) {
    await dynamo.send(new DeleteCommand({ TableName: config.table, Key: { id } }));
    logError(id, e);
    return problem(503, "could not queue the document; retry");
  }
  await markSent(job);
  return json(202, view(job), location);
}

/** Records that the job's message is in the queue, so a resend never takes the record over as orphaned. */
async function markSent(job: Job): Promise<void> {
  try {
    await dynamo.send(
      new UpdateCommand({
        TableName: config.table,
        Key: { id: job.id },
        UpdateExpression: "SET sentAt = :sentAt",
        ConditionExpression: "updatedAt = :updatedAt",
        ExpressionAttributeValues: { ":sentAt": new Date().toISOString(), ":updatedAt": job.updatedAt },
      }),
    );
  } catch (e) {
    // the job is queued either way: a worker already moved the record on, or a resend REQUEUE_AFTER_SECONDS from now
    // queues it once more
    if (!(e instanceof ConditionalCheckFailedException)) logError(job.id, e);
  }
}

async function read(id: string): Promise<Job | undefined> {
  const found = await dynamo.send(new GetCommand({ TableName: config.table, Key: { id } }));
  return found.Item as Job | undefined;
}

/** The existing job, as it is now; 503 when its record is gone (the request that wrote it could not queue it). */
function duplicate(job: Job | undefined, location: Record<string, string>): APIGatewayProxyStructuredResultV2 {
  return job ? json(200, { ...view(job), duplicate: true }, location) : problem(503, "could not queue the document; retry");
}

function logError(id: string, e: unknown): void {
  console.error(JSON.stringify({ level: "error", route: "submit", id, error: e instanceof Error ? e.name : "unknown" }));
}

/** Writes the job record, new or over `seen` if it is unchanged; false when another request got there first. */
async function claim(job: Job, seen?: Job): Promise<boolean> {
  const condition = seen
    ? {
        ConditionExpression: "#status = :status AND updatedAt = :updatedAt",
        ExpressionAttributeNames: { "#status": "status" },
        ExpressionAttributeValues: { ":status": seen.status, ":updatedAt": seen.updatedAt },
      }
    : { ConditionExpression: "attribute_not_exists(id)" };
  try {
    await dynamo.send(new PutCommand({ TableName: config.table, Item: job, ...condition }));
    return true;
  } catch (e) {
    if (e instanceof ConditionalCheckFailedException) return false;
    throw e;
  }
}

function retryable(job: Job, now: Date): boolean {
  if (job.status === "failed") return (job.requeues ?? 0) < config.maxRequeues;
  const age = now.getTime() - Date.parse(job.updatedAt);
  return job.status === "queued" && job.sentAt === undefined && age >= config.requeueAfterSeconds * 1000;
}
