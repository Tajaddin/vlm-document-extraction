# Model card: receipt and invoice extraction with local vision-language models

## What it is

A comparison, and a service built on its winner: local vision-language models (through Ollama) read a receipt or
invoice image and return a fixed JSON schema; a review step flags extractions for a person. The models are
off-the-shelf, not fine-tuned; what this project contributes is the measurement, the schema and prompt design, and
the serving path.

| Approach | Model (Ollama tag) | Where it ran on an RTX 4060 8 GB at an 8K context |
|---|---|---|
| OCR + LLM (baseline) | RapidOCR (PP-OCRv6, ONNX, CPU) + `qwen2.5:7b` | text model 100% on the GPU |
| VLM | `qwen3-vl:8b-instruct` | 19% on the CPU |
| VLM | `qwen2.5vl:7b` | 15% on the CPU |
| VLM | `qwen3.5:4b` | 100% on the GPU |

Settings for every run: temperature 0, seed 0, 8,192-token context, at most 2,048 output tokens, prompt p2 (the
receipt prompt is unchanged since p1), receipt schema with the common keys required and nullable (ADR 0002).

## Intended use

Pre-filling accounts-payable fields for a person to confirm. Not straight-through processing: on the best
configuration 58% of held-out invoices had every field right, and the review flags catch only some of the rest.

## Data

- **CORD v2** (CC BY 4.0): real Indonesian receipts, photographed. Test split, 100 receipts, scored once; prompt and
  schema work on the validation split.
- **FATURA v2** (CC BY 4.0): synthetic invoices in 50 layouts. Test: 10 invoices from each of the 10 layouts its
  authors hold out; few-shot examples and dev work only from the other 40.

## Results (test sets, `reports/eval/`, paired comparisons in `reports/eval/analysis.json`)

**Receipts (CORD v2), Donut field F1 and tree-edit accuracy:**

| Run | Field F1 (95% CI) | TED accuracy | p50 / p95 per receipt | Failed |
|---|---|---|---|---|
| qwen3-vl:8b-instruct, zero-shot | **0.680** (0.651-0.711) | 0.788 | 12.5 s / 31.9 s | 0 |
| qwen2.5vl:7b, zero-shot | 0.619 (0.570-0.667) | 0.669 | 8.4 s / 23.9 s | 0 |
| qwen3-vl:8b-instruct, two-shot | 0.606 (0.540-0.666) | 0.570 | 12.6 s / 20.4 s | 22 |
| qwen3.5:4b, two-shot | 0.474 (0.407-0.537) | 0.338 | 4.8 s / 20.7 s | 25 |
| OCR + LLM | 0.336 (0.295-0.379) | 0.229 | 7.2 s / 16.0 s | 2 |
| qwen3.5:4b, zero-shot | 0.223 (0.184-0.263) | 0.472 | 5.3 s / 12.0 s | 3 |

**Invoices (FATURA v2, 10 unseen layouts), field F1 after normalising amounts and dates:**

| Run | Field F1 (95% CI) | Invoices fully correct | p50 per invoice |
|---|---|---|---|
| qwen3-vl:8b-instruct, two-shot | **0.964** (0.954-0.974) | 58% | 7.2 s |
| qwen3.5:4b, two-shot | 0.946 (0.933-0.958) | 45% | 3.0 s |
| qwen2.5vl:7b, zero-shot | 0.943 (0.932-0.953) | 32% | 4.5 s |
| qwen3-vl:8b-instruct, zero-shot | 0.928 (0.914-0.941) | 25% | 5.9 s |
| qwen3.5:4b, zero-shot | 0.926 (0.915-0.936) | 15% | 2.6 s |
| OCR + LLM | 0.922 (0.911-0.933) | 22% | 3.9 s |

**What the paired comparisons say** (difference in field F1 on documents both runs answered, 95% bootstrap
interval):

- On photographed receipts a VLM roughly doubles the OCR pipeline: qwen3-vl +0.34 (+0.30 to +0.38).
- On clean digital invoices the OCR pipeline nearly keeps up zero-shot: qwen3-vl +0.006 (-0.012 to +0.023, not
  significant), qwen2.5vl +0.020 (+0.006 to +0.034).
- Two examples from other layouts help on unseen layouts: qwen3-vl +0.036 on invoices (+0.022 to +0.052). On
  receipts they make no measurable difference to qwen3-vl (+0.015, -0.022 to +0.050, on the 78 receipts where both
  runs answered) but fix the 4B model's formatting (+0.32, +0.25 to +0.38).

## Failure modes

- **Context overflow with few-shot receipts:** with two example receipts the request needed up to 10,506 tokens;
  at an 8K context, 20 of 100 prompts were refused (qwen3-vl) and 17 (qwen3.5:4b). A 16K context would fit them and push more of the
  model onto the CPU of an 8 GB card. The failed receipts count as misses in the tables above.
- **Brace artifacts in qwen3.5:4b:** zero-shot, 716 of its 1,296 receipt values were wrapped in braces
  ("{24,000}"); two examples cut that to 33 of 1,005.
- **Invented amounts:** models add up line items into a subtotal or total the invoice does not print; the p2 prompt
  reduced this on the dev set (35 to 24 invented values) but did not remove it.
- **Partial CPU offload:** the 7-8B models do not fit an 8 GB GPU whole at this context, which is most of their
  latency; the 4B model runs entirely on the GPU and is two to three times faster.

## Review flags (`vde.checks`)

On invoices the flags caught 25-56% of extractions with any error, depending on the run, and 30-88% of flagged
invoices were in fact wrong. One flag misfires on the data itself: FATURA's synthetic due dates fall before the
issue date on 32 of the 100 test invoices, so "due before issue" fires on correct extractions too. On receipts
nearly every extraction has at least one field wrong under exact matching, so the flags (all of which were right
when they fired) catch 11-38% of a very large set. The flags are a safety net, not a guarantee.

## Limits

- One GPU, one machine, 100 documents per test set: intervals of a few points; differences inside them are ties.
- FATURA is synthetic and its arithmetic and dates are not always consistent.
- Gemini on Vertex AI is implemented behind the same interface but was not run (it bills a Google Cloud project).
