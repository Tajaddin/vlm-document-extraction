# Research notes (2026-10-22)

What I looked at before shaping this project, with sources. Read with the postings in `G:\Jobs\applications`.

## What the target employers ask for

- Akoncagua AI (AI/ML engineer intern, Lakeland): "document-intelligence pipelines for invoices, receipts, contracts,
  and financial statements", "evaluation harnesses that measure extraction accuracy", "multimodal AI".
- Ancestry (Data Science co-op, AI document understanding): OCR, transcription, NER, "evaluate the performance of
  multi-modal models in zero-shot and few-shot learning scenarios", LoRA/QLoRA, Hugging Face, and "Google Gemini
  API, Vertex AI, AWS ... SageMaker, Bedrock is a plus".
- Campbell's, Moffitt, Artera: multimodal models in agentic systems and in clinical data.
- College Board (SWE I): "cost-effective serverless solutions using AWS", TypeScript and Node.js.

## Models that fit an 8 GB GPU (local, free)

- Ollama ships Qwen3-VL in 2B, 4B and 8B with separate `-instruct` and `-thinking` tags; at q4_K_M the 8B is 6.2 GB
  ([ollama.com/library/qwen3-vl](https://ollama.com/library/qwen3-vl/tags)). The untagged names point at the thinking
  variants, which spend their budget on hidden reasoning (a known problem for JSON output), so the instruct tags are
  the ones to use. Qwen2.5-VL 3B and 7B are also in the library.
- Third-party comparisons put Qwen2.5-VL-7B and Qwen3-VL-8B close on DocVQA (85.4 vs 84.9) and advise q4_K_M or
  better for OCR-heavy work ([bestllmfor.com](https://bestllmfor.com/vs/llama32-vision-vs-qwen-vl/),
  [Qwen3-VL on Ollama](https://bestllmfor.com/guide/qwen3-vl-vision-local-ollama/)); a cloud benchmark on SROIE
  receipts reports 90.6% for Qwen3-VL-30B ([Doubleword](https://docs.doubleword.ai/batches/structured-extraction)).
  None of these were run on this hardware or this data, which is why this project measures its own.

## Data (public, licensed)

- **CORD v2** (CLOVA AI): 1,000 Indonesian receipts with a hierarchical parse (menu items, subtotal, tax, total);
  800/100/100 train/validation/test; CC BY 4.0
  ([dataset card](https://huggingface.co/datasets/naver-clova-ix/cord-v2), [repo](https://github.com/clovaai/cord)).
  The standard metrics are Donut's field-level F1 and tree-edit-distance accuracy.
- **FATURA** (Zenodo, v2, 2023): 10,000 invoice images in 50 layouts with 24 annotated field classes; CC BY 4.0
  ([record 10371464](https://zenodo.org/records/10371464), [paper](https://arxiv.org/abs/2311.11856)). Its layouts
  repeat, so the honest test holds whole layouts out.

## Serverless without paying, and without LocalStack

LocalStack's community image needs an account and auth token since 2026-03-23 (the `latest` tag moved to a unified
image; see [testcontainers-java#11568](https://github.com/testcontainers/testcontainers-java/issues/11568),
[spring-cloud-aws#1586](https://github.com/awspring/spring-cloud-aws/issues/1586)). **Floci** is an MIT-licensed
replacement on the same port with Lambda (real containers), API Gateway v2 HTTP APIs, S3 notifications, SQS and
DynamoDB, and it is tested against the Terraform AWS provider
([floci-io/floci](https://github.com/floci-io/floci); 27K stars, release 2.3.0 on 2026-10-15). So the same
Terraform can be applied to Floci in CI and to AWS later.

## Vertex AI

Gemini 2.5 Flash on Vertex AI is listed at about $0.30 per million input tokens and $2.50 per million output, half
that in batch mode ([Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)): the 200
evaluation documents here would cost a few cents. That still bills an account, so the Vertex path is built and
tested against recorded responses, and run only with the owner's go-ahead.

Update 2026-10-23: with that go-ahead, the live run found Gemini 2.5 Flash no longer served to a new project
(404 in us-central1 and global); it used Gemini 3.8 Flash on the global endpoint instead
([DEPLOY](docs/DEPLOY.md#vertex-ai-backlog-18)).
