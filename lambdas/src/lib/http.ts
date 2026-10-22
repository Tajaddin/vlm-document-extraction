import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";
import { createHash, timingSafeEqual } from "node:crypto";

export function json(statusCode: number, body: unknown, headers: Record<string, string> = {}): APIGatewayProxyStructuredResultV2 {
  return {
    statusCode,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...headers },
    body: JSON.stringify(body),
  };
}

export function problem(statusCode: number, detail: string): APIGatewayProxyStructuredResultV2 {
  return json(statusCode, { error: detail });
}

/** Header lookup that ignores case (API Gateway v2 lower-cases names, but tests and other callers may not). */
export function header(event: APIGatewayProxyEventV2, name: string): string | undefined {
  const wanted = name.toLowerCase();
  for (const [key, value] of Object.entries(event.headers)) {
    if (key.toLowerCase() === wanted) return value;
  }
  return undefined;
}

/** True when the request's X-API-Key hashes to the configured digest; compared in constant time. */
export function authorized(event: APIGatewayProxyEventV2, apiKeySha256: string): boolean {
  const key = header(event, "x-api-key");
  if (!key) return false;
  const got = createHash("sha256").update(key, "utf8").digest();
  const want = Buffer.from(apiKeySha256, "hex");
  return want.length === got.length && timingSafeEqual(got, want);
}

/** One JSON line per request: ids, route, status and timing; never bodies or headers. */
export function logRequest(fields: Record<string, unknown>): void {
  console.log(JSON.stringify({ level: "info", ...fields }));
}
