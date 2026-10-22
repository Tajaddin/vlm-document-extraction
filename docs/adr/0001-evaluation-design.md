# 0001. Evaluation design: held-out layouts, a dev split for prompt work, test scored once

Date: 2026-10-22. Status: accepted.

## Context

Extraction demos usually show a model on documents that look like the ones it was tuned on. The question this
project has to answer is narrower and harder: on a layout the system has never seen, how often is each field right,
and how does a vision-language model compare with the OCR pipeline it would replace? A number that leaks the test
documents into prompt work, or into few-shot examples, answers a different question.

## Decision

1. **Two public datasets with different failure modes.** CORD v2 (real Indonesian receipts, photographed, noisy)
   and FATURA v2 (synthetic invoices rendered cleanly in 50 layouts). Both CC BY 4.0, both pinned by the publisher's
   checksum (`evals/data-manifest.json`).
2. **FATURA is split by layout, using its authors' split** (`Strat2_Split.txt`): test documents are 10 per layout
   from the 10 held-out layouts (100 invoices, fixed seed); few-shot examples and dev documents come only from the
   40 training layouts. Seller details are constant within a layout, so a random split would let examples give
   the answer away.
3. **CORD's validation split is the dev set** (prompt and schema choices, few-shot examples); its test split (100
   receipts) is scored once per configuration, after the choices are frozen.
4. **Metrics anyone can compare.** Receipts: Donut's field-level F1 and normalised tree-edit-distance accuracy,
   reimplemented and checked equal to Donut's own evaluator on seeded errors (`scripts/check_metrics_against_donut.py`,
   run in CI). Invoices: per-field accuracy after normalising amounts, dates and names, the same pair-based F1, and
   the share of invoices with every field right. 95% bootstrap intervals over documents for every headline number.
5. **A value the document does not print is an error.** Models that add up line items into a subtotal the invoice
   never prints are wrong, not helpful: an accounts-payable system must not invent amounts. Checked by hand on the
   first dev case (Template 3, instance 143: no subtotal printed; both models produced 585.38).
6. **Same conditions for every approach:** temperature 0, fixed seed, the same JSON schema, one GPU, latency
   percentiles that leave out the first (model-loading) document.

## Consequences

- 100 documents per test set gives intervals of a few points; differences smaller than that are reported as ties.
- FATURA is synthetic: its arithmetic does not always add up (subtotal + tax differs from the printed total), so
  arithmetic review checks are measured on CORD's real receipts, not on FATURA.
- The OCR baseline uses one text model (qwen2.5:7b); a stronger text model would move the baseline, and the README
  says so.
