#!/usr/bin/env bash
# Prompt and schema work on the dev documents only (CORD validation, FATURA training layouts). Nothing here touches
# a test document. Reports land in reports/dev/.
set -euo pipefail
out=reports/dev
uv run vde eval --dataset cord --split dev --limit 30 --variant required --out-dir "$out"
uv run vde eval --dataset cord --split dev --limit 30 --variant optional --out-dir "$out"
uv run vde eval --dataset cord --split dev --limit 30 --approach ocr --out-dir "$out"
uv run vde eval --dataset fatura --split dev --out-dir "$out"
uv run vde eval --dataset fatura --split dev --approach ocr --out-dir "$out"
uv run vde summarize --out-dir "$out"
