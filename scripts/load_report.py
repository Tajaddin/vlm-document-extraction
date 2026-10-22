"""Turn k6's end-of-test summary into the committed load report: per arrival rate, how many submits went through and
their latency, plus the duplicate and status routes. Labels everything as emulator numbers."""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
from typing import Any


def trend(metrics: dict[str, Any], name: str) -> dict[str, Any] | None:
    m = metrics.get(name)
    if not m:
        return None
    v = m["values"]
    return {
        k: round(v[s], 1) for k, s in (("p50_ms", "p(50)"), ("p95_ms", "p(95)"), ("p99_ms", "p(99)"), ("max_ms", "max"))
    } | {"count": int(v["count"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("summary", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--rates", default="5,10,20")
    ap.add_argument("--step", type=int, default=60)
    a = ap.parse_args()
    data = json.loads(a.summary.read_text(encoding="utf-8"))
    metrics = data["metrics"]
    steps = {}
    for rate in a.rates.split(","):
        sub = metrics.get(f"submit_ms{{step:{rate}}}") or {}
        steps[rate] = {"offered_per_s": int(rate), "seconds": a.step}
        if sub:
            steps[rate] |= {
                k: round(sub["values"][s], 1)
                for k, s in (("p50_ms", "p(50)"), ("p95_ms", "p(95)"), ("p99_ms", "p(99)"))
            }
    checks = {c["name"]: {"passes": c["passes"], "fails": c["fails"]} for c in data["root_group"]["checks"]}
    failed = metrics.get("http_req_failed", {}).get("values", {})
    report = {
        "what": "k6 against the serverless intake (API Gateway -> TypeScript Lambda -> DynamoDB, S3, SQS) on the Floci emulator",
        "caveat": "emulator on one machine (Lambda in local containers): shows the code path's behaviour under load, not AWS capacity",
        "machine": {"cpu": platform.processor(), "cpus": os.cpu_count(), "os": platform.platform(terse=True)},
        "submit": trend(metrics, "submit_ms"),
        "duplicate_submit": trend(metrics, "duplicate_ms"),
        "status": trend(metrics, "status_ms"),
        "submit_by_rate": steps,
        "http_req_failed_rate": round(failed.get("rate", 0.0), 4),
        "dropped_iterations": int(metrics.get("dropped_iterations", {}).get("values", {}).get("count", 0)),
        "checks": checks,
    }
    a.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
