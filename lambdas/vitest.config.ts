import { createHash } from "node:crypto";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    // the handlers read their configuration when the module loads, as they do in a Lambda container
    env: {
      BUCKET: "vde-documents",
      TABLE: "vde-jobs",
      QUEUE_URL: "https://sqs.us-east-1.amazonaws.com/000000000000/vde-jobs",
      // the tests send the key "test-key"; the function only ever sees its digest
      API_KEY_SHA256: createHash("sha256").update("test-key").digest("hex"),
      MAX_BYTES: "1024",
    },
    coverage: { provider: "v8", include: ["src/**"], reporter: ["text", "lcov"] },
  },
});
