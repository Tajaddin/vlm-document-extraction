// Configuration from the function's environment (set by Terraform). Read once per container.

export interface Config {
  bucket: string;
  table: string;
  queueUrl: string;
  /** SHA-256 (hex) of the API key; the key itself never reaches the function. */
  apiKeySha256: string;
  maxBytes: number;
  /** Largest image, in pixels, the worker is asked to decode. */
  maxPixels: number;
  jobTtlDays: number;
  /** A job still "queued" this long after it was written, never marked as sent, has no message behind it. */
  requeueAfterSeconds: number;
  /** A resend queues a failed job again at most this many times; after that the failure stands. */
  maxRequeues: number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const read = (name: string): string => {
    const value = env[name];
    if (!value) throw new Error(`missing environment variable ${name}`);
    return value;
  };
  return {
    bucket: read("BUCKET"),
    table: read("TABLE"),
    queueUrl: env.QUEUE_URL ?? "",
    apiKeySha256: read("API_KEY_SHA256").toLowerCase(),
    maxBytes: Number(env.MAX_BYTES ?? 4 * 1024 * 1024),
    maxPixels: Number(env.MAX_PIXELS ?? 50_000_000),
    jobTtlDays: Number(env.JOB_TTL_DAYS ?? 30),
    requeueAfterSeconds: Number(env.REQUEUE_AFTER_SECONDS ?? 900),
    maxRequeues: Number(env.MAX_REQUEUES ?? 2),
  };
}
