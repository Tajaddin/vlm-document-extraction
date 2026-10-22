.PHONY: help install lint format typecheck test test-data check secret-scan fetch verify data-report dev-runs test-runs summarize metrics-check backlog \
        lambdas up infra-up infra-down test-integration load alerts-test worker-up

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

lambdas:            ## typecheck, lint, test and bundle the TypeScript Lambdas
	cd lambdas && npm ci && npm run typecheck && npm run lint && npm test && npm run build

up:                 ## the Floci AWS emulator
	docker compose up -d --wait floci

infra-up: lambdas   ## Terraform on Floci: API Gateway, Lambdas, S3, SQS (+ DLQ), DynamoDB
	terraform -chdir=infra/terraform/envs/floci init -input=false && terraform -chdir=infra/terraform/envs/floci apply -auto-approve -input=false

infra-down:
	terraform -chdir=infra/terraform/envs/floci destroy -auto-approve -input=false

test-integration:   ## worker against Floci (Testcontainers) and the deployed stack end to end
	AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test uv run pytest -m integration -v

worker-up:          ## the worker in Docker, reading the queue the Terraform created
	VDE_QUEUE_URL=$$(terraform -chdir=infra/terraform/envs/floci output -raw queue_url) \
	VDE_BUCKET=$$(terraform -chdir=infra/terraform/envs/floci output -raw bucket) \
	docker compose --profile worker up -d --build worker

load:               ## k6 on the emulated intake at 5, 10, 20 and 40 requests/s (reports/load/)
	bash scripts/load.sh 5,10,20,40 60

alerts-test:        ## promtool unit tests for the alert rules
	docker run --rm -v "$(CURDIR)/observability:/w" -w /w --entrypoint promtool prom/prometheus:v3.5.0 test rules alerts_test.yml
