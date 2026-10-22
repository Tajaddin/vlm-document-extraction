.PHONY: help install lint format typecheck test test-data check secret-scan fetch verify data-report dev-runs test-runs summarize metrics-check backlog

help:               ## this list
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

install:            ## Python deps incl. the OCR, worker and Vertex extras
	uv sync --all-extras

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy

test:               ## unit tests
	uv run pytest -m "not integration and not data" --cov --cov-report=term-missing

test-data:          ## tests on the downloaded datasets (make fetch first)
	uv run pytest -m data -v

check: lint typecheck test

secret-scan:        ## run before every push
	bash scripts/secret_scan.sh

fetch:              ## CORD v2 and FATURA, checked against the publishers' checksums (~1.2 GB)
	uv run vde fetch

verify:
	uv run vde verify

data-report:        ## FATURA gold-field parse rates (reports/data/)
	uv run vde data-report

metrics-check:      ## the metrics against Donut's own evaluator (reports/metrics-vs-donut.json)
	uv run --with zss --with nltk python scripts/check_metrics_against_donut.py

dev-runs:           ## prompt and schema work on the dev documents only (needs Ollama and the models)
	bash scripts/dev_runs.sh

test-runs:          ## every approach on both test sets (about 2-3 hours on an RTX 4060)
	bash scripts/test_runs.sh

summarize:
	uv run vde summarize

backlog:            ## issues, milestones and the board on GitHub from docs/agile/backlog.json
	uv run python scripts/agile/sync_backlog.py --board && uv run python scripts/agile/board.py sprints
