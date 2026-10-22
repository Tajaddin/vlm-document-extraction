// The job record in DynamoDB, shared by the submit and status functions (the Python worker writes the same shape).

export type Kind = "receipt" | "invoice";
export type Status = "queued" | "processing" | "done" | "failed";

export interface Job {
  id: string;
  kind: Kind;
  status: Status;
  key: string;
  contentType: string;
  bytes: number;
  createdAt: string;
  updatedAt: string;
  expiresAt: number;
  result?: Record<string, unknown>;
  review?: string[];
  model?: string;
  seconds?: number;
  error?: string;
}

export const ID = /^[0-9a-f]{32}$/;

export function isKind(value: string | undefined): value is Kind {
  return value === "receipt" || value === "invoice";
}

/** The public view of a job: no storage keys. */
export function view(job: Job): Record<string, unknown> {
  const { key, expiresAt, ...rest } = job;
  return rest;
}
