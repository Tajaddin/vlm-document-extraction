#!/usr/bin/env bash
# k6 against the intake on the Floci emulator, then a compact report and an empty queue again.
#   bash scripts/load.sh [rates] [seconds per step]       e.g. bash scripts/load.sh 5,10,20 60
# Needs `docker compose up -d floci` and `make infra-up`. Writes reports/load/intake-emulator.json.
set -euo pipefail
rates=${1:-5,10,20}
step=${2:-60}
cd "$(git rev-parse --show-toplevel)"
tf=infra/terraform/envs/floci
api_id=$(terraform -chdir="$tf" output -raw api_id)
api_key=$(terraform -chdir="$tf" output -raw api_key)
queue=$(terraform -chdir="$tf" output -raw queue_url)
work=.cache/load/in out=.cache/load/out  # repository-relative: Python on Windows does not read Git Bash paths
rm -rf .cache/load && mkdir -p "$work" "$out"
uv run --no-sync python -c "
from pathlib import Path
from vde.data.fatura import Fatura
Path('$work/invoice.jpg').write_bytes(Fatura(Path('data')).document(2, 5, 'test').image)
"
cp load/intake.js "$work/"
mount_work=$(pwd)/$work mount_out=$(pwd)/$out
if command -v cygpath >/dev/null 2>&1; then  # Git Bash on Windows
  export MSYS_NO_PATHCONV=1
  mount_work=$(cygpath -m "$mount_work") mount_out=$(cygpath -m "$mount_out")
fi
docker run --rm --network vde_default -v "$mount_work:/load:ro" -v "$mount_out:/out" \
  -e TARGET=http://floci:4566 -e API_HOST="$api_id.execute-api.localhost.floci.io" -e API_KEY="$api_key" \
  -e RATES="$rates" -e STEP_S="$step" grafana/k6:1.8.2 run --quiet /load/intake.js || echo "k6 thresholds failed (see report)"
mkdir -p reports/load
uv run --no-sync python scripts/load_report.py "$out/summary.json" reports/load/intake-emulator.json --rates "$rates" --step "$step"
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test uv run --no-sync python -c "
import boto3
boto3.client('sqs', endpoint_url='http://127.0.0.1:4566', region_name='us-east-1').purge_queue(QueueUrl='$queue')
print('queue purged')
"
