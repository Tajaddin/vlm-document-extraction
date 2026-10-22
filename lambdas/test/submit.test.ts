import { ConditionalCheckFailedException } from "@aws-sdk/client-dynamodb";
import { PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { SendMessageCommand, SQSClient } from "@aws-sdk/client-sqs";
import { DeleteCommand, DynamoDBDocumentClient, GetCommand, PutCommand } from "@aws-sdk/lib-dynamodb";
import { mockClient } from "aws-sdk-client-mock";
import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { handler } from "../src/submit.js";
import { event, JPEG, PNG } from "./event.js";

const dynamo = mockClient(DynamoDBDocumentClient);
const s3 = mockClient(S3Client);
const sqs = mockClient(SQSClient);
const jpegId = createHash("sha256").update("invoice").update(":").update(JPEG).digest("hex").slice(0, 32);

beforeEach(() => {
  dynamo.reset();
  s3.reset();
  sqs.reset();
  vi.spyOn(console, "log").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

const body = (r: { body?: string | undefined }): Record<string, unknown> => JSON.parse(r.body ?? "{}") as Record<string, unknown>;

describe("submit", () => {
  it("stores the image, records the job and queues it", async () => {
    const r = await handler(event());
    expect(r.statusCode).toBe(202);
    expect(body(r)).toMatchObject({ id: jpegId, kind: "invoice", status: "queued", bytes: JPEG.length });
    expect(body(r)).not.toHaveProperty("key");
    expect(r.headers?.location).toBe(`/v1/documents/${jpegId}`);

    const put = dynamo.commandCalls(PutCommand)[0]?.args[0].input;
    expect(put?.ConditionExpression).toBe("attribute_not_exists(id)");
    const object = s3.commandCalls(PutObjectCommand)[0]?.args[0].input;
    expect(object).toMatchObject({ Bucket: "vde-documents", Key: `incoming/${jpegId}.jpg`, ContentType: "image/jpeg" });
    const message = sqs.commandCalls(SendMessageCommand)[0]?.args[0].input;
    expect(JSON.parse(message?.MessageBody ?? "")).toEqual({ id: jpegId, kind: "invoice", key: `incoming/${jpegId}.jpg` });
  });

  it("returns the existing job for the same document instead of queueing it twice", async () => {
    dynamo.on(PutCommand).rejects(new ConditionalCheckFailedException({ message: "exists", $metadata: {} }));
    dynamo.on(GetCommand).resolves({ Item: { id: jpegId, kind: "invoice", status: "done", key: "k", expiresAt: 1, result: { total: 1 } } });
    const r = await handler(event());
    expect(r.statusCode).toBe(200);
    expect(body(r)).toMatchObject({ id: jpegId, status: "done", duplicate: true, result: { total: 1 } });
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(0);
    expect(s3.commandCalls(PutObjectCommand)).toHaveLength(0);
  });

  it("removes the job record when it cannot be queued, so a retry starts over", async () => {
    sqs.on(SendMessageCommand).rejects(new Error("queue down"));
    const r = await handler(event());
    expect(r.statusCode).toBe(503);
    expect(dynamo.commandCalls(DeleteCommand)[0]?.args[0].input.Key).toEqual({ id: jpegId });
  });

  it("accepts a receipt and a PNG", async () => {
    const r = await handler(event({ queryStringParameters: { kind: "receipt" }, headers: { "X-Api-Key": "test-key", "Content-Type": "image/png" }, body: PNG.toString("base64") }));
    expect(r.statusCode).toBe(202);
    expect(body(r)).toMatchObject({ kind: "receipt", contentType: "image/png" });
  });

  it.each([
    ["no key", { headers: { "content-type": "image/jpeg" } }, 401],
    ["a wrong key", { headers: { "x-api-key": "nope", "content-type": "image/jpeg" } }, 401],
    ["an unknown kind", { queryStringParameters: { kind: "contract" } }, 400],
    ["a PDF", { headers: { "x-api-key": "test-key", "content-type": "application/pdf" } }, 415],
    ["no body", { body: undefined }, 400],
    ["bytes that are not the declared type", { body: PNG.toString("base64") }, 415],
    ["a body over the size limit", { body: Buffer.concat([JPEG, Buffer.alloc(2000)]).toString("base64") }, 413],
  ] as const)("refuses %s", async (_name, overrides, status) => {
    const r = await handler(event(overrides));
    expect(r.statusCode).toBe(status);
    expect(dynamo.commandCalls(PutCommand)).toHaveLength(0);
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(0);
  });

  it("logs the request without its body or headers", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    await handler(event());
    const line = String(log.mock.calls.at(-1)?.[0]);
    expect(JSON.parse(line)).toMatchObject({ route: "submit", status: 202, requestId: "req-1" });
    expect(line).not.toContain("test-key");
  });
});
