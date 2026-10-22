// Configuration from the function's environment (set by Terraform). Read once per container.

export interface Config {
  bucket: string;
  table: string;
  queueUrl: string;
  /** SHA-256 (hex) of the API key; the key itself never reaches the function. */
  apiKeySha256: string;
  maxBytes: number;
  jobTtlDays: number;
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
    jobTtlDays: Number(env.JOB_TTL_DAYS ?? 30),
  };
}
