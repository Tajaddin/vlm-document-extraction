import { DynamoDBDocumentClient, GetCommand } from "@aws-sdk/lib-dynamodb";
import { mockClient } from "aws-sdk-client-mock";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { handler } from "../src/status.js";
import { pixels, sniff } from "../src/lib/image.js";
import { loadConfig } from "../src/lib/config.js";
import { event, frame, jpeg, png } from "./event.js";

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

  it("reads the pixel count from the image header without decoding it", () => {
    expect(pixels(jpeg(595, 841), "image/jpeg")).toBe(595 * 841);
    expect(pixels(png(864, 1296), "image/png")).toBe(864 * 1296);
    const body = jpeg(40, 30).subarray(20);
    expect(pixels(Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xff]), body]), "image/jpeg")).toBe(1200); // fill bytes
    expect(pixels(Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0x01]), body]), "image/jpeg")).toBeUndefined(); // a marker with no segment
    expect(pixels(Buffer.from([0xff, 0xd8, 0xff, 0xda, 0x00, 0x08, 0x01, 0x01]), "image/jpeg")).toBeUndefined(); // scan before frame
    expect(pixels(Buffer.from([0xff, 0xd8, 0x00, 0x00, 0x00, 0x00]), "image/jpeg")).toBeUndefined();
  });

  it("refuses a header that hides a frame from it but not from the decoders", () => {
    // PIL and Go skip the marker FF 00 as two bytes and take the 10000 x 7000 frame; read as a segment, FF 00 would
    // jump 65,474 bytes onto a 100 x 100 frame that the decoders see as the inside of an APP1 segment
    const app1 = Buffer.alloc(65533);
    frame(100, 100).copy(app1, 65476 - 27);
    const hidden = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0x00]), frame(10000, 7000), Buffer.from([0xff, 0xe1, 0xff, 0xff]), app1, jpeg(1, 1).subarray(39)]);
    expect(pixels(hidden, "image/jpeg")).toBeUndefined();
  });

  it("refuses to start without its configuration", () => {
    expect(() => loadConfig({})).toThrow("BUCKET");
    expect(loadConfig({ BUCKET: "b", TABLE: "t", API_KEY_SHA256: "AB" })).toMatchObject({ apiKeySha256: "ab", maxBytes: 4194304, queueUrl: "" });
  });
});
