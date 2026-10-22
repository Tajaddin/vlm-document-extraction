import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    // the handlers read their configuration when the module loads, as they do in a Lambda container
    env: {
      BUCKET: "vde-documents",
      TABLE: "vde-jobs",
      QUEUE_URL: "https://sqs.us-east-1.amazonaws.com/000000000000/vde-jobs",
      // sha256("test-key")
      API_KEY_SHA256: "62af8704764faf8ea82fc61ce9c4c3908b6cb97d463a634e9e587d7c885db0ef",
      MAX_BYTES: "1024",
    },
    coverage: { provider: "v8", include: ["src/**"], reporter: ["text", "lcov"] },
  },
});
