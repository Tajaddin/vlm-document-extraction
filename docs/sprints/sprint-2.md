# Sprint 2 retro: VLM extraction measured

Dates: 2026-10-22. Milestone: [Sprint 2 - VLM extraction measured](https://github.com/Tajaddin/vlm-document-extraction/milestone/2).

**Goal:** local vision-language models extract the same fields zero-shot and few-shot, measured against the
baseline on the same held-out documents, with review flags and a model card. **Met.** Its pull request follows
Sprint 3's: the GPU these runs needed was in use elsewhere for part of the day.

## Delivered

| Issue | Points | Result |
|---|---|---|
| #7 VLMs zero-shot | 3 | qwen3-vl:8b-instruct, qwen2.5vl:7b and qwen3.5:4b on both test sets |
| #8 few-shot | 3 | two examples from the dev split (CORD) or other layouts (FATURA), measured against zero-shot on the same documents |
| #9 review flags | 2 | measured on every run: wrong extractions caught, flags that were right, flags on the gold labels |
| #10 report and model card | 2 | `reports/eval/` (one report per run, `analysis.json` with paired comparisons), the model card |

10 of 10 points done.

## Before the test sets: what the dev documents decided

- **Receipt schema** (`reports/dev/cord-dev/`): common keys required and nullable beat optional keys, field F1
  0.716 vs 0.496 on 30 validation receipts.
- **Invoice prompt p2** (`reports/dev/fatura-dev/`): error analysis on the 40 dev invoices found subtotals and totals
  the invoice does not print (added up by the model) and "Ship to" names as the buyer. p2 says not to. On the same
  invoices: invented values 35 to 24, invoices fully correct 32.5% to 42.5%, F1 0.916 to 0.928 (inside the
  interval), missed values 10 to 13. Frozen before any test document was scored with a VLM.
- **A gold-label gap** found the same way: some layouts file the amount due as `AMOUNT_DUE`, not `TOTAL`; the gold
  now falls back to it (400 invoices of 10,000).

## Measured (test sets, 100 documents each)

| | CORD receipts, field F1 | FATURA invoices (unseen layouts), field F1 |
|---|---|---|
| OCR + LLM | 0.336 (0.295-0.379) | 0.922 (0.911-0.933) |
| qwen3-vl:8b, zero-shot | 0.680 (0.651-0.711) | 0.928 (0.914-0.941) |
| qwen2.5vl:7b, zero-shot | 0.619 (0.570-0.667) | 0.943 (0.932-0.953) |
| qwen3.5:4b, zero-shot | 0.223 (0.184-0.263) | 0.926 (0.915-0.936) |
| qwen3-vl:8b, two-shot | 0.606 (0.540-0.666), 22 failed | **0.964** (0.954-0.974) |
| qwen3.5:4b, two-shot | 0.474 (0.407-0.537), 25 failed | 0.946 (0.933-0.958) |

Paired comparisons and what they mean are in the model card; the short version: a VLM doubles the OCR pipeline on
photographed receipts, OCR nearly keeps up on clean invoices zero-shot, and examples from other layouts are what
put the VLM clearly ahead there.

## What went well

- Deciding the schema and the prompt on dev documents, and recording each prediction's prompt version, means the
  test numbers were scored once, with choices made before seeing them.
- The paired analysis separated two things a single F1 table blurred: few-shot receipts failing for lack of
  context, and few-shot not helping the 8B model on the receipts that fit.

## What did not

- **Few-shot receipts overflowed the 8K context** in about a fifth of cases (up to 10,506 tokens). The setting was
  chosen to fit the 8 GB GPU; a 16K context would fit them and push more of the model onto the CPU. Reported, not
  re-run with changed settings.
- **qwen3.5:4b wraps receipt values in braces** zero-shot (716 of 1,296 values); the spike showed it on one receipt
  and the full run on 63 of 100.
- **The review flags are weak:** 25-56% of wrong invoices caught; one flag misfires on FATURA's own data (32 of 100
  test invoices have a due date before the issue date).
- My first time estimate for the test runs was based on the slowest per-document times; the runs took 2 h 27 min.

## Carried into Sprint 4

- README and release.
