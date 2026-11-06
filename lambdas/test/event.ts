import type { APIGatewayProxyEventV2 } from "aws-lambda";

const be16 = (n: number): number[] => [n >>> 8, n & 0xff];
const be32 = (n: number): number[] => [n >>> 24, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff];

/** A JPEG's header up to its frame: start of image, a JFIF segment, then the start-of-frame segment with the size. */
export function jpeg(width: number, height: number, frame = 0xc0): Buffer {
  const jfif = [0xff, 0xe0, ...be16(16), 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00];
  const sof = [0xff, frame, ...be16(17), 0x08, ...be16(height), ...be16(width), 0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01];
  return Buffer.from([0xff, 0xd8, ...jfif, ...sof]);
}

/** A PNG's signature and its IHDR chunk (8-bit RGB). */
export function png(width: number, height: number): Buffer {
  const ihdr = [...be32(13), 0x49, 0x48, 0x44, 0x52, ...be32(width), ...be32(height), 0x08, 0x02, 0x00, 0x00, 0x00, 0, 0, 0, 0];
  return Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...ihdr]);
}

export const JPEG = jpeg(595, 841);
export const PNG = png(864, 1296);

/** Any field may be replaced, or removed by passing undefined. */
export type Overrides = { [K in keyof APIGatewayProxyEventV2]?: APIGatewayProxyEventV2[K] | undefined };

/** An API Gateway HTTP API (payload 2.0) event, the shape the functions receive. */
export function event(overrides: Overrides = {}): APIGatewayProxyEventV2 {
  const base: APIGatewayProxyEventV2 = {
    version: "2.0",
    routeKey: "POST /v1/documents",
    rawPath: "/v1/documents",
    rawQueryString: "",
    headers: { "x-api-key": "test-key", "content-type": "image/jpeg" },
    isBase64Encoded: true,
    body: JPEG.toString("base64"),
    requestContext: {
      accountId: "000000000000",
      apiId: "api",
      domainName: "localhost",
      domainPrefix: "api",
      http: { method: "POST", path: "/v1/documents", protocol: "HTTP/1.1", sourceIp: "127.0.0.1", userAgent: "vitest" },
      requestId: "req-1",
      routeKey: "POST /v1/documents",
      stage: "$default",
      time: "22/Oct/2026:06:00:00 +0000",
      timeEpoch: 1792648800000,
    },
  };
  return { ...base, ...overrides } as APIGatewayProxyEventV2;
}
