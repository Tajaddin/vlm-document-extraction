import type { APIGatewayProxyEventV2 } from "aws-lambda";

export const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46]);
export const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]);

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
