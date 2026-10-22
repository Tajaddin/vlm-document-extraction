#!/usr/bin/env bash
# Every configuration on both held-out test sets, once each. Choices were frozen on the dev documents first
# (scripts/dev_runs.sh, ADR 0002). Resumable: a run that stops picks up where its predictions file ends.
#   bash scripts/test_runs.sh            all of it (about 2.5 hours on an RTX 4060)
#   bash scripts/test_runs.sh baseline   the OCR + LLM baseline only
set -euo pipefail
which=${1:-all}
for dataset in cord fatura; do
  uv run vde eval --dataset "$dataset" --approach ocr
  [ "$which" = baseline ] && continue
  for model in qwen3-vl:8b-instruct qwen2.5vl:7b qwen3.5:4b; do
    uv run vde eval --dataset "$dataset" --model "$model"
  done
  for model in qwen3-vl:8b-instruct qwen3.5:4b; do
    uv run vde eval --dataset "$dataset" --model "$model" --shots 2
  done
done
uv run vde summarize
