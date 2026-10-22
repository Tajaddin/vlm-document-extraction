import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { S3Client } from "@aws-sdk/client-s3";
import { SQSClient } from "@aws-sdk/client-sqs";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";

// Created once per container and reused across invocations. The SDK picks up AWS_ENDPOINT_URL by itself, which the
// Floci emulator sets in every function container; S3 then needs path-style addressing, which real AWS does not.
const emulated = Boolean(process.env.AWS_ENDPOINT_URL);

export const s3 = new S3Client({ forcePathStyle: emulated });
export const sqs = new SQSClient({});
export const dynamo = DynamoDBDocumentClient.from(new DynamoDBClient({}), {
  marshallOptions: { removeUndefinedValues: true },
});
