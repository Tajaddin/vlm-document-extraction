"""Analysis of the test-set runs, from their committed reports and predictions:

- paired comparisons: each method against the OCR + LLM baseline, and two-shot against zero-shot, on the documents
  where both runs produced an answer, with a 95% bootstrap interval on the difference in field F1;
- why runs failed (context overflow, truncation) and how often;
- the brace artifact (values like "{24,000}") per run;
- the review flags: wrong extractions caught, flags that fired on correct ones, flags on the gold labels.

    uv run python scripts/analyze_eval.py --out reports/eval/analysis.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from vde.metrics import Counts, micro_f1

ROOT = Path("reports/eval")


def load(dataset: str, run: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report = json.loads((ROOT / f"{dataset}-test" / f"{run}.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (ROOT / f"{dataset}-test" / f"{run}.predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return report, rows


def paired(a: dict[str, Any], b: dict[str, Any], n: int = 2000, seed: int = 0) -> dict[str, Any]:
    """F1 of b minus F1 of a on the documents both answered, with a bootstrap interval over those documents."""
    da = {d["id"]: d for d in a["per_document"]}
    db = {d["id"]: d for d in b["per_document"]}
    ids = [i for i in da if i in db and not da[i]["error"] and not db[i]["error"]]
    ca = [Counts(da[i]["tp"], da[i]["fp"], da[i]["fn"]) for i in ids]
    cb = [Counts(db[i]["tp"], db[i]["fp"], db[i]["fn"]) for i in ids]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ids), size=(n, len(ids)))
    diffs = [micro_f1([cb[j] for j in row]) - micro_f1([ca[j] for j in row]) for row in idx]
    low, high = np.percentile(diffs, [2.5, 97.5])
    return {
        "documents": len(ids),
        "f1_a": round(micro_f1(ca), 4),
        "f1_b": round(micro_f1(cb), 4),
        "difference": round(micro_f1(cb) - micro_f1(ca), 4),
        "difference_95ci": [round(float(low), 4), round(float(high), 4)],
        "significant": bool(low > 0 or high < 0),
    }


def leaves(o: Any) -> list[str]:
    if isinstance(o, dict):
        return [x for v in o.values() for x in leaves(v)]
    if isinstance(o, list):
        return [x for v in o for x in leaves(v)]
    return [o] if isinstance(o, str) and o else []


def failure_kind(error: str) -> str:
    if "exceeds the available context size" in error:
        return "context_overflow"
    return error.split(":", maxsplit=1)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "analysis.json")
    a = ap.parse_args()
    out: dict[str, Any] = {}
    for dataset in ("cord", "fatura"):
        suffix = "-required" if dataset == "cord" else ""
        runs = sorted(p.stem for p in (ROOT / f"{dataset}-test").glob("*.json"))
        loaded = {r: load(dataset, r) for r in runs}
        baseline = f"ocr-qwen2.5-7b-0shot{suffix}"
        section: dict[str, Any] = {"vs_ocr_baseline": {}, "two_shot_vs_zero_shot": {}, "runs": {}}
        for run, (report, rows) in loaded.items():
            values = [v for r in rows if r["fields"] for v in leaves(r["fields"])]
            braces = [v for v in values if "{" in v or "}" in v]
            section["runs"][run] = {
                "field_f1": report["field_f1"],
                "failures": dict(Counter(failure_kind(str(r["error"])) for r in rows if r["error"])),
                "values_with_braces": f"{len(braces)}/{len(values)}",
                "placement": report["config"]["environment"].get("placement"),
                "review": {
                    k: report["review"][k]
                    for k in (
                        "documents_wrong",
                        "documents_flagged",
                        "wrong_caught",
                        "flagged_that_were_wrong",
                        "flags_on_gold_labels",
                    )
                },
            }
            if run != baseline:
                section["vs_ocr_baseline"][run] = paired(loaded[baseline][0], report)
            if "-2shot" in run:
                zero = run.replace("-2shot", "-0shot")
                section["two_shot_vs_zero_shot"][run] = paired(loaded[zero][0], report)
        out[dataset] = section
    a.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({d: {k: v for k, v in s.items() if k != "runs"} for d, s in out.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
