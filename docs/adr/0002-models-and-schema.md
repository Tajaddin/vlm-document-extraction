# 0002. Three local VLMs, a required-but-nullable receipt schema, and a cap on output

Date: 2026-10-22. Status: accepted.

## Context

The models must run on the one GPU available (RTX 4060, 8 GB) through Ollama, answer in JSON, and be compared on
equal terms. Three questions came up before any test document was scored.

## Decision

1. **Models (spike, issue #2).** One CORD validation receipt through four candidates with a JSON schema, warm
   latency on the second call: qwen3.5:4b 3.8 s, qwen2.5vl:7b 4.0 s, qwen3-vl:8b-instruct 5.8 s, qwen3.5:9b 6.2 s.
   qwen3.5:9b did not fit in VRAM (Ollama placed 14% of it on the CPU) and is left out. Only qwen3-vl:8b-instruct
   read `total_price` right on that receipt; qwen2.5vl:7b put the total into `cashprice`. The evaluation runs
   qwen3-vl:8b-instruct (main), qwen2.5vl:7b and qwen3.5:4b; the `-instruct` tag, because thinking variants spend
   their budget on hidden reasoning. A single receipt decides nothing about accuracy; it only decides what is
   worth a full run.
2. **Receipt schema: common keys required, values nullable.** With every key optional, the spike's models left out
   keys they could see (`cnt`) because constrained decoding lets them stop early. On 30 CORD validation receipts
   with qwen3-vl:8b-instruct (`reports/dev/cord-dev/`): required-but-nullable field F1 **0.716** (95% CI
   0.643-0.781) against **0.496** (0.443-0.552) for optional, better on 26 of 30 receipts, at a p50 of 10.8 s
   against 8.7 s. Invoices already used required, nullable fields.
3. **Output capped at 2,048 tokens** (#20). One OCR + LLM answer on the dev set ran to 8,055 tokens of whitespace
   (194 s) because Ollama sets no limit and the JSON grammar allows unlimited whitespace. The longest real answer
   on the dev sets was 482 tokens. A cut-off answer counts as a failure, not as a result.
4. **Deterministic settings**: temperature 0, seed 0, 8,192-token context, the same prompt version for every
   model, recorded in each report.

## Consequences

- The choice of schema was made on validation receipts only; the test split had not been scored when it was made.
- A 4-bit 8B model is what fits. Larger models (30B class) would likely read better and would need about 24 GB of
  VRAM, or Vertex AI (ADR 0003, backlog #18).
