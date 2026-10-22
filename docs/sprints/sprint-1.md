# Sprint 1 retro: data and evaluation harness

Dates: 2026-10-22. Milestone: [Sprint 1 - Data and evaluation harness](https://github.com/Tajaddin/vlm-document-extraction/milestone/1).

**Goal:** both datasets load with verified checksums, gold labels are derived and checked, the metrics are tested,
and an OCR + LLM baseline is measured on the held-out test sets. **Met.**

## Delivered

| Issue | Points | Result |
|---|---|---|
| #1 scaffold | 2 | uv project, settings, JSON logs, CI with ruff, mypy, tests, gitleaks, pip-audit |
| #2 spike | 1 | four candidate VLMs on one receipt; the committed rerun of the spike and its ADR arrived with Sprint 3's pull request |
| #3 datasets | 3 | CORD v2 and FATURA pinned by the publishers' checksums; FATURA's authors' layout split |
| #4 gold fields | 3 | FATURA fields parsed from the annotation text; every printed field parses |
| #5 metrics | 3 | Donut's field F1 and tree-edit accuracy, equal to Donut's own evaluator on 100 receipts (checked in CI) |
| #6 OCR baseline | 3 | RapidOCR + qwen2.5:7b with the same schema, measured on both test sets |
| #20 bug: output padding | 1 | answers capped at 2,048 tokens; a cut-off answer counts as a failure |

16 of 16 points done (15 planned, 1 added for the bug).

## Measured

- **Metrics vs Donut** (`reports/metrics-vs-donut.json`): field F1 identical (0.79016), tree-edit accuracy equal on
  every one of 100 perturbed receipts.
- **Gold** (`reports/data/fatura-gold.json`): every field parses on every invoice that prints it (10,000 invoices).
- **OCR + LLM baseline on the test sets** (RTX 4060 8 GB, qwen2.5:7b fully on the GPU):

  | Test set | Field F1 (95% CI) | Second metric | p50 per document |
  |---|---|---|---|
  | CORD v2 receipts (100) | 0.336 (0.295-0.379) | tree-edit accuracy 0.229 | 7.2 s (OCR 0.9 s, LLM 6.4 s) |
  | FATURA invoices, 10 held-out layouts (100) | 0.922 (0.911-0.933) | 22% of invoices fully correct | 3.9 s (OCR 1.2 s, LLM 2.7 s) |

  The two numbers are far apart for a reason: FATURA's invoices are clean digital renders that OCR reads well,
  CORD's receipts are crumpled photos with Indonesian abbreviations.

## What went well

- Checking the metrics against Donut's own code, not against hand cases alone, means the receipt numbers are
  comparable with the literature.
- Spot-checking the gold labels against the images before trusting them: a 100% parse rate could have hidden
  wrong values; it did not.

## What did not

- **A model answer ran to 8,055 tokens of whitespace** (194 s) because Ollama sets no output limit and the JSON
  grammar allows unlimited whitespace (#20). Found in the dev runs, fixed before any test document was scored.
- The scaffold commit first carried a command whose module belonged to a later sprint; caught before pushing.
- The dev and test runs were interrupted once while the GPU was needed for something else; the runner resumes from
  its predictions file, so nothing was lost or scored twice.

## Carried into Sprint 2

- The vision-language models on the same documents, zero-shot and few-shot.
