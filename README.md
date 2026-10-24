# vlm-document-extraction

[![CI](https://github.com/Tajaddin/vlm-document-extraction/actions/workflows/ci.yml/badge.svg)](https://github.com/Tajaddin/vlm-document-extraction/actions/workflows/ci.yml)

Receipt and invoice extraction with **local vision-language models**, measured against the **OCR + LLM pipeline**
they would replace, on public datasets with **whole layouts held out**, and served behind a **serverless intake**
(API Gateway, TypeScript Lambdas, S3, SQS, DynamoDB) with a GPU worker. Everything runs locally and free: the models
in Ollama, AWS on the Floci emulator, from the same Terraform that would deploy to AWS.

## The answer

On one RTX 4060 (8 GB), 100 test documents per set, 95% intervals from resampling documents
([model card](docs/MODEL-CARD.md), `reports/eval/`):

| | Photographed receipts (CORD v2) | Clean invoices, 10 unseen layouts (FATURA) |
|---|---|---|
| OCR + LLM (RapidOCR + qwen2.5:7b) | field F1 0.336 (0.295-0.379) | 0.922 (0.911-0.933) |
| Best VLM, zero-shot | **0.680** (0.651-0.711), qwen3-vl:8b | 0.943 (0.932-0.953), qwen2.5vl:7b |
| Best VLM, two examples from other layouts | no measurable gain | **0.964** (0.954-0.974), qwen3-vl:8b, 58% of invoices fully right |
| Cloud reference: Gemini 3.8 Flash on Vertex AI, zero-shot | **0.837** (0.799-0.871) | **0.987** (0.982-0.992), 79% of invoices fully right |

- **Where the image is hard, the VLM wins outright:** on receipts qwen3-vl roughly doubles the OCR pipeline
  (+0.34, 95% CI +0.30 to +0.38, paired).
- **Where the document is clean, OCR nearly keeps up:** on digital invoices the zero-shot difference is a couple of
  points or less; two worked examples, even from other layouts, are what lift the VLM clearly ahead (+0.036).
- **The small model needs examples:** qwen3.5:4b wraps 55% of its zero-shot receipt values in braces ("{24,000}");
  two examples fix most of it (+0.32 F1).
- **Few-shot costs context:** two example receipts push a request to 10,506 tokens; at an 8K context a fifth of
  them were refused. On an 8 GB card the 7-8B models already run 15-19% on the CPU.
- **A hosted model is the ceiling, and it is cheap:** Gemini 3.8 Flash (run 2026-10-23, same prompt, schema and
  scorer) beats every local model on both sets, with intervals that do not overlap theirs: +0.50 over OCR + LLM on
  receipts (paired, 98 documents both answered). Measured usage was 1,602 input and 114 output tokens per invoice
  and 2,132 / 179 per receipt: about $0.39 for all 200 documents at the October 2026 list prices ($0.75 / $3.75 per
  million), p50 2.3-2.9 s per document over the internet. The local models keep the documents on the machine.

## What it shows

| Area | Where |
|---|---|
| Vision-language models (Qwen3-VL, Qwen2.5-VL, Qwen3.5) through Ollama with a JSON schema; few-shot with image examples | `src/vde/extract` |
| An evaluation that would survive review: publisher checksums, held-out layouts, a dev split, Donut's metrics checked against Donut's own code, paired bootstrap comparisons | `src/vde/evaluate.py`, `scripts/analyze_eval.py`, [ADR 0001](docs/adr/0001-evaluation-design.md) |
| AWS Lambda (TypeScript, Node 22) behind API Gateway, S3, SQS with a dead-letter queue, DynamoDB; idempotent submits | `lambdas/`, [ADR 0003](docs/adr/0003-serverless-intake-gpu-worker.md) |
| Terraform: one module, an emulator environment applied in CI and an AWS environment validated, linted and scanned | `infra/terraform`, [ADR 0004](docs/adr/0004-floci-for-local-aws.md) |
| A GPU worker with review flags, Prometheus metrics, alert rules with promtool tests, a runbook | `src/vde/worker`, `observability/`, [RUNBOOK](docs/RUNBOOK.md) |
| Gemini on Vertex AI behind the same interface, scored on both test sets | `src/vde/extract/vertex.py`, [DEPLOY](docs/DEPLOY.md) |
| Scrum: backlog, 4 sprints, a pull request and a retro per sprint | [board](https://github.com/users/Tajaddin/projects/5), [retros](docs/sprints) |

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run it

Needs Docker, [uv](https://docs.astral.sh/uv/), Node 22, Terraform and [Ollama](https://ollama.com).

```bash
uv sync --all-extras
uv run vde fetch                                   # CORD v2 and FATURA, checked against the publishers' checksums
ollama pull qwen3-vl:8b-instruct
uv run vde eval --dataset fatura --limit 10        # a quick run on the held-out invoices
bash scripts/test_runs.sh                          # every configuration on both test sets (2 h 27 min here)
uv run python scripts/analyze_eval.py              # the paired comparisons
```

The serverless side on the emulator:

```bash
docker compose up -d --wait floci
cd lambdas && npm ci && npm run build && cd ..
terraform -chdir=infra/terraform/envs/floci init && terraform -chdir=infra/terraform/envs/floci apply
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test uv run pytest -m integration   # worker and end-to-end tests
```

## Other measurements

- **Serverless intake on the emulator** (`reports/load/intake-emulator.json`, k6 at 5, 10, 20 and 40 new documents
  a second for a minute each): 4,503 submits, 0 failed requests; submit p50 9.2 ms, p99 59.5 ms (71.4 ms at 40/s);
  the slowest requests were Lambda cold starts. Emulator numbers on one machine: they show the code path under load,
  not AWS capacity.
- **Tests**: 67 Python unit tests, 4 integration tests (the worker against Floci via Testcontainers, the deployed
  stack end to end), 3 tests on the downloaded data, 16 TypeScript tests with 100% line coverage, 8 promtool
  scenarios; CI with 9 jobs including Terraform applied to Floci, trivy on the image and the Terraform, gitleaks,
  pip-audit and npm audit.

## Limits

- One GPU, 100 documents per test set: differences inside the intervals are ties.
- FATURA is synthetic: its totals do not always add up and its due dates fall before the issue date on 32% of the
  test invoices.
- The review flags catch a third to half of wrong invoices: a person still checks.
- AWS is not exercised live (it needs the owner's account; steps in [DEPLOY](docs/DEPLOY.md)). Vertex AI was run
  once on each test set; Gemini 2.5 Flash, the model first planned, was no longer served to a new project.

MIT licensed. Data: CORD v2 and FATURA, both CC BY 4.0.
