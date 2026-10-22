// POST /v1/documents?kind=invoice|receipt with the image as the body.
//
// The job id is a hash of the kind and the bytes, so a client that retries (or sends the same document twice) gets the
// same job back instead of paying for a second extraction. DynamoDB's conditional put is the lock: only the request
// that creates the record queues the job. If queueing fails, the record is removed again so a retry can start over.

import { PutObjectCommand } from "@aws-sdk/client-s3";
import { SendMessageCommand } from "@aws-sdk/client-sqs";
import { ConditionalCheckFailedException } from "@aws-sdk/client-dynamodb";
import { DeleteCommand, GetCommand, PutCommand } from "@aws-sdk/lib-dynamodb";
import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";
import { createHash } from "node:crypto";

import { dynamo, s3, sqs } from "./lib/clients.js";
import { loadConfig } from "./lib/config.js";
import { authorized, header, json, logRequest, problem } from "./lib/http.js";
import { EXTENSIONS, isImageType, sniff } from "./lib/image.js";
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

  try {
    await dynamo.send(new PutCommand({ TableName: config.table, Item: job, ConditionExpression: "attribute_not_exists(id)" }));
  } catch (e) {
    if (!(e instanceof ConditionalCheckFailedException)) throw e;
    const existing = await dynamo.send(new GetCommand({ TableName: config.table, Key: { id } }));
    return json(200, { ...view(existing.Item as Job), duplicate: true }, { location: `/v1/documents/${id}` });
  }

  try {
    await s3.send(new PutObjectCommand({ Bucket: config.bucket, Key: key, Body: bytes, ContentType: contentType }));
    await sqs.send(new SendMessageCommand({ QueueUrl: config.queueUrl, MessageBody: JSON.stringify({ id, kind, key }) }));
  } catch (e) {
    await dynamo.send(new DeleteCommand({ TableName: config.table, Key: { id } }));
    console.error(JSON.stringify({ level: "error", route: "submit", id, error: e instanceof Error ? e.name : "unknown" }));
    return problem(503, "could not queue the document; retry");
  }
  return json(202, view(job), { location: `/v1/documents/${id}` });
}
