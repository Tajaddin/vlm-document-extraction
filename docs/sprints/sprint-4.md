# Sprint 4 retro: documents and release

Dates: 2026-10-22. Milestone: [Sprint 4 - Observability and release](https://github.com/Tajaddin/vlm-document-extraction/milestone/4).

**Goal:** the worker and the API have metrics and tested alerts, a Vertex AI adapter exists, and the measured
results are documented and released. **Met.** The alerts (#15) and the Vertex AI adapter (#16) were built in
Sprint 3, next to the worker they belong to; this sprint is the README and the release.

## Delivered

| Issue | Points | Result |
|---|---|---|
| #17 README and release | 2 | the answer first (where a VLM beats OCR and where it does not), every number with its report, how to run it, limits; v1.0.0 |

2 of 2 points done here; #15 and #16 (5 points) moved to Sprint 3.

## What went well

- The README leads with the finding, including the parts that do not favour VLMs: on clean invoices zero-shot, the
  OCR pipeline nearly keeps up.

## What did not

- The sprints merged out of order (1, 3, 2, 4) because the evaluation needed the GPU while it was in use elsewhere.
  Each pull request still closed only its own sprint's issues, and the retros say why.

## Left in the backlog

- #18: run the Vertex AI extractor on both test sets (needs a Google Cloud project with billing; a few cents).
- #19: apply the Terraform to an AWS account.
