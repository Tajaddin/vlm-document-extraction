import { ConditionalCheckFailedException } from "@aws-sdk/client-dynamodb";
import { PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { SendMessageCommand, SQSClient } from "@aws-sdk/client-sqs";
import { DeleteCommand, DynamoDBDocumentClient, GetCommand, PutCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";
import { mockClient } from "aws-sdk-client-mock";
import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { handler } from "../src/submit.js";
import { beforeData, event, frame, ihdr, JPEG, jpeg, PNG, png } from "./event.js";

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
    const sent = dynamo.commandCalls(UpdateCommand)[0]?.args[0].input;
    expect(sent).toMatchObject({ Key: { id: jpegId }, UpdateExpression: "SET sentAt = :sentAt", ConditionExpression: "updatedAt = :updatedAt" });
    expect(sent?.ExpressionAttributeValues?.[":updatedAt"]).toBe(put?.Item?.updatedAt);
  });

  it.each([
    ["a worker already moved the record on", new ConditionalCheckFailedException({ message: "changed", $metadata: {} }), 0],
    ["DynamoDB refused the write", new Error("throttled"), 1],
  ])("answers 202 when the job is queued but not marked as sent (%s)", async (_name, error, logged) => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    dynamo.on(UpdateCommand).rejects(error);
    const r = await handler(event());
    expect(r.statusCode).toBe(202);
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(1);
    expect(log).toHaveBeenCalledTimes(logged);
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

  const exists = new ConditionalCheckFailedException({ message: "exists", $metadata: {} });
  const ago = (seconds: number): string => new Date(Date.now() - seconds * 1000).toISOString();

  it.each([
    ["a failed job", { status: "failed", error: "truncated", updatedAt: ago(5) }],
    ["a job left queued without a message", { status: "queued", updatedAt: ago(901) }],
  ])("queues %s again, taking the record over only if it is unchanged", async (_name, seen) => {
    dynamo.on(PutCommand).rejectsOnce(exists).resolves({});
    dynamo.on(GetCommand).resolves({ Item: { id: jpegId, kind: "invoice", key: "k", expiresAt: 1, ...seen } });
    const r = await handler(event());
    expect(r.statusCode).toBe(202);
    expect(body(r)).toMatchObject({ id: jpegId, status: "queued" });
    expect(body(r)).not.toHaveProperty("error");
    const takeover = dynamo.commandCalls(PutCommand)[1]?.args[0].input;
    expect(takeover?.ConditionExpression).toBe("#status = :status AND updatedAt = :updatedAt");
    expect(takeover?.ExpressionAttributeValues).toEqual({ ":status": seen.status, ":updatedAt": seen.updatedAt });
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(1);
  });

  it("does not queue a job again while its message waits in a backed-up queue", async () => {
    dynamo.on(PutCommand).rejectsOnce(exists).resolves({});
    dynamo.on(GetCommand).resolves({ Item: { id: jpegId, kind: "invoice", status: "queued", key: "k", expiresAt: 1, updatedAt: ago(3600), sentAt: ago(3600) } });
    const r = await handler(event());
    expect(r.statusCode).toBe(200);
    expect(body(r)).toMatchObject({ status: "queued", duplicate: true });
    expect(body(r)).not.toHaveProperty("sentAt");
    expect(dynamo.commandCalls(PutCommand)).toHaveLength(1);
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(0);
  });

  it("does not queue a job twice while its message is still waiting", async () => {
    dynamo.on(PutCommand).rejects(exists);
    dynamo.on(GetCommand).resolves({ Item: { id: jpegId, kind: "invoice", status: "queued", key: "k", expiresAt: 1, updatedAt: ago(60) } });
    const r = await handler(event());
    expect(r.statusCode).toBe(200);
    expect(body(r)).toMatchObject({ status: "queued", duplicate: true });
    expect(dynamo.commandCalls(PutCommand)).toHaveLength(1);
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(0);
  });

  it("leaves a failed job to the request that took it over first, and answers with the job as it now is", async () => {
    dynamo.on(PutCommand).rejects(exists);
    dynamo
      .on(GetCommand)
      .resolvesOnce({ Item: { id: jpegId, kind: "invoice", status: "failed", error: "truncated", key: "k", expiresAt: 1, updatedAt: ago(5) } })
      .resolves({ Item: { id: jpegId, kind: "invoice", status: "queued", key: "k", expiresAt: 1, updatedAt: ago(0) } });
    const r = await handler(event());
    expect(r.statusCode).toBe(200);
    expect(body(r)).toMatchObject({ status: "queued", duplicate: true });
    expect(body(r)).not.toHaveProperty("error");
    expect(dynamo.commandCalls(PutCommand)).toHaveLength(2);
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(0);
  });

  it("does not take a DynamoDB error for a duplicate", async () => {
    dynamo.on(PutCommand).rejects(new Error("throttled"));
    await expect(handler(event())).rejects.toThrow("throttled");
    expect(dynamo.commandCalls(GetCommand)).toHaveLength(0);
  });

  it("asks for a retry when the record it collided with is gone", async () => {
    dynamo.on(PutCommand).rejects(exists);
    dynamo.on(GetCommand).resolves({});
    expect((await handler(event())).statusCode).toBe(503);
    expect(sqs.commandCalls(SendMessageCommand)).toHaveLength(0);
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
    ["a JPEG over the pixel limit", { body: jpeg(10000, 6000).toString("base64") }, 413],
    ["a progressive JPEG over the pixel limit", { body: jpeg(10000, 6000, 0xc2).toString("base64") }, 413],
    ["a PNG over the pixel limit", { headers: { "x-api-key": "test-key", "content-type": "image/png" }, body: png(65535, 65535).toString("base64") }, 413],
    ["a JPEG with a small frame header in front of a large one", { body: beforeData(jpeg(100, 100), frame(10000, 7000)).toString("base64") }, 415],
    ["a PNG with a small IHDR chunk in front of a large one", { headers: { "x-api-key": "test-key", "content-type": "image/png" }, body: beforeData(png(100, 100), ihdr(10000, 7000)).toString("base64") }, 415],
    ["a JPEG that ends before its frame header", { body: JPEG.subarray(0, 20).toString("base64") }, 415],
    ["a PNG without its IHDR chunk", { headers: { "x-api-key": "test-key", "content-type": "image/png" }, body: PNG.subarray(0, 12).toString("base64") }, 415],
    ["a PNG that ends before its image data", { headers: { "x-api-key": "test-key", "content-type": "image/png" }, body: PNG.subarray(0, 33).toString("base64") }, 415],
    ["an image that says it has no pixels", { body: jpeg(595, 0).toString("base64") }, 415],
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
