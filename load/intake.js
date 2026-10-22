// k6 load test of the serverless intake on the Floci emulator (scripts/load.sh runs it).
// Every submit carries a unique document, so each one takes the full path: Lambda, DynamoDB conditional put, S3, SQS.
// These are emulator numbers on one machine; they say where the code's own limits are, not what AWS would do.
import http from "k6/http";
import { check } from "k6";
import { Trend } from "k6/metrics";

const TARGET = __ENV.TARGET || "http://floci:4566";
const HOST = __ENV.API_HOST; // <api id>.execute-api.localhost.floci.io: Floci routes HTTP APIs by host
const KEY = __ENV.API_KEY;
const RATES = (__ENV.RATES || "5,10,20").split(",").map(Number);
const STEP_S = Number(__ENV.STEP_S || 60);
const image = new Uint8Array(open("/load/invoice.jpg", "b"));

const submitMs = new Trend("submit_ms", true);
const duplicateMs = new Trend("duplicate_ms", true);
const statusMs = new Trend("status_ms", true);

export const options = {
  scenarios: Object.fromEntries(
    RATES.map((rate, i) => [
      `submit_${rate}`,
      {
        executor: "constant-arrival-rate",
        rate,
        timeUnit: "1s",
        duration: `${STEP_S}s`,
        startTime: `${i * (STEP_S + 10)}s`,
        preAllocatedVUs: rate * 2,
        maxVUs: rate * 10,
        exec: "submit",
        tags: { step: String(rate) },
      },
    ]),
  ),
  // k6 computes a tagged sub-metric only when a threshold names it; these make the per-rate latencies appear
  thresholds: {
    http_req_failed: ["rate<0.01"],
    ...Object.fromEntries(RATES.map((rate) => [`submit_ms{step:${rate}}`, ["p(99)<30000"]])),
  },
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max", "count"],
};

const headers = (type) => ({ Host: HOST, "x-api-key": KEY, ...(type ? { "content-type": type } : {}) });

function unique() {
  // the original image, then 16 random bytes after its end-of-image marker: a new job id, still a JPEG
  const body = new Uint8Array(image.length + 16);
  body.set(image);
  for (let i = 0; i < 16; i++) body[image.length + i] = Math.floor(Math.random() * 256);
  return body.buffer;
}

export function submit() {
  const body = unique();
  const first = http.post(`${TARGET}/v1/documents?kind=invoice`, body, { headers: headers("image/jpeg"), tags: { route: "submit" } });
  check(first, { "202 accepted": (r) => r.status === 202 });
  submitMs.add(first.timings.duration);
  if (first.status !== 202) return;
  const id = first.json("id");
  const again = http.post(`${TARGET}/v1/documents?kind=invoice`, body, { headers: headers("image/jpeg"), tags: { route: "duplicate" } });
  check(again, { "duplicate is the same job": (r) => r.status === 200 && r.json("id") === id });
  duplicateMs.add(again.timings.duration);
  const status = http.get(`${TARGET}/v1/documents/${id}`, { headers: headers(), tags: { route: "status" } });
  check(status, { "status readable": (r) => r.status === 200 });
  statusMs.add(status.timings.duration);
}

export function handleSummary(data) {
  return { "/out/summary.json": JSON.stringify(data, null, 2) };
}
