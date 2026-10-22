import { DynamoDBDocumentClient, GetCommand } from "@aws-sdk/lib-dynamodb";
import { mockClient } from "aws-sdk-client-mock";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { handler } from "../src/status.js";
import { sniff } from "../src/lib/image.js";
import { loadConfig } from "../src/lib/config.js";
import { event } from "./event.js";

const dynamo = mockClient(DynamoDBDocumentClient);
const ID = "0123456789abcdef0123456789abcdef";
const get = (id: string, headers: Record<string, string> = { "x-api-key": "test-key" }) =>
  handler(event({ routeKey: "GET /v1/documents/{id}", pathParameters: { id }, headers, body: undefined }));

beforeEach(() => {
  dynamo.reset();
  vi.spyOn(console, "log").mockImplementation(() => undefined);
});

describe("status", () => {
  it("returns the job without its storage key", async () => {
    dynamo.on(GetCommand).resolves({ Item: { id: ID, status: "done", kind: "invoice", key: "incoming/x.jpg", expiresAt: 9, result: { total: 575.33 }, review: [] } });
    const r = await get(ID);
    expect(r.statusCode).toBe(200);
    const body = JSON.parse(r.body ?? "{}") as Record<string, unknown>;
    expect(body).toEqual({ id: ID, status: "done", kind: "invoice", result: { total: 575.33 }, review: [] });
  });

  it("answers 401, 400 and 404", async () => {
    dynamo.on(GetCommand).resolves({}); // what DynamoDB returns for a key it does not have
    expect((await get(ID, {})).statusCode).toBe(401);
    expect((await get("../etc/passwd")).statusCode).toBe(400);
    expect((await get(ID)).statusCode).toBe(404);
    expect(dynamo.commandCalls(GetCommand)).toHaveLength(1);
  });
});

describe("helpers", () => {
  it("recognises image types by their bytes", () => {
    expect(sniff(Buffer.from([0xff, 0xd8, 0xff]))).toBe("image/jpeg");
    expect(sniff(Buffer.from("%PDF-1.7"))).toBeUndefined();
  });

  it("refuses to start without its configuration", () => {
    expect(() => loadConfig({})).toThrow("BUCKET");
    expect(loadConfig({ BUCKET: "b", TABLE: "t", API_KEY_SHA256: "AB" })).toMatchObject({ apiKeySha256: "ab", maxBytes: 4194304, queueUrl: "" });
  });
});
