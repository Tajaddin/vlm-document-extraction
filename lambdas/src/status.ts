// GET /v1/documents/{id}: the job's status and, once done, the extracted fields and any review flags.

import { GetCommand } from "@aws-sdk/lib-dynamodb";
import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";

import { dynamo } from "./lib/clients.js";
import { loadConfig } from "./lib/config.js";
import { authorized, json, logRequest, problem } from "./lib/http.js";
import { ID, view, type Job } from "./lib/jobs.js";

const config = loadConfig();

export async function handler(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  const started = Date.now();
  const response = await status(event);
  logRequest({ route: "status", requestId: event.requestContext.requestId, status: response.statusCode, ms: Date.now() - started });
  return response;
}

async function status(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  if (!authorized(event, config.apiKeySha256)) return problem(401, "missing or wrong X-API-Key");
  const id = event.pathParameters?.id ?? "";
  if (!ID.test(id)) return problem(400, "id must be 32 hex characters");
  const found = await dynamo.send(new GetCommand({ TableName: config.table, Key: { id } }));
  if (!found.Item) return problem(404, "no such document");
  return json(200, view(found.Item as Job));
}
