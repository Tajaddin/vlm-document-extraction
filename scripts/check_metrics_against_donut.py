"""Check vde.metrics against Donut's own evaluator on CORD gold with seeded errors.

    uv run --with zss --with nltk python scripts/check_metrics_against_donut.py --out reports/metrics-vs-donut.json

Downloads `JSONParseEvaluator` from clovaai/donut (MIT) at a pinned commit into a temporary directory, so neither
Donut nor `zss` (licence not stated) is a dependency of this project; both are only used here, to check.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import random
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from vde.data import cord
from vde.metrics import field_counts, micro_f1, ted_accuracy

DONUT_COMMIT = "4cfcf972560e1a0f26eb3e294c8fc88a0d336626"
URL = f"https://raw.githubusercontent.com/clovaai/donut/{DONUT_COMMIT}/donut/util.py"


def donut_evaluator() -> Any:
    source = httpx.get(URL, timeout=60).raise_for_status().text
    cls = source[source.index("class JSONParseEvaluator") :]
    header = "import zss\nfrom zss import Node\nfrom nltk import edit_distance\nfrom typing import Any, Dict, List, Tuple, Union\n\n"
    path = Path(tempfile.mkdtemp()) / "donut_eval.py"
    path.write_text(header + cls, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("donut_eval", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.JSONParseEvaluator()


def perturb(gold: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Append a character to 15% of values, drop 10% of keys, replace the total block in 20% of receipts."""
    pred = copy.deepcopy(gold)

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for key in list(o):
                r = rng.random()
                if isinstance(o[key], str):
                    if r < 0.15:
                        o[key] = o[key] + "1"
                    elif r < 0.25:
                        del o[key]
                else:
                    walk(o[key])
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(pred)
    if rng.random() < 0.2:
        pred["total"] = {"total_price": "999"}
    return pred


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("reports/metrics-vs-donut.json"))
    a = ap.parse_args()
    golds = [d.gold for d in cord.load(a.data_dir, "validation")]
    rng = random.Random(1)
    preds = [perturb(g or {}, rng) for g in golds]
    evaluator = donut_evaluator()
    donut_acc = [evaluator.cal_acc(p, g) for p, g in zip(preds, golds, strict=True)]
    ours_acc = [ted_accuracy(p, g) for p, g in zip(preds, golds, strict=True)]
    report = {
        "what": "vde.metrics vs Donut's JSONParseEvaluator on CORD v2 validation gold with seeded errors",
        "donut": URL,
        "documents": len(golds),
        "field_f1": {
            "donut": evaluator.cal_f1(preds, golds),
            "vde": micro_f1([field_counts(p, g) for p, g in zip(preds, golds, strict=True)]),
        },
        "ted_accuracy_mean": {"donut": sum(donut_acc) / len(donut_acc), "vde": sum(ours_acc) / len(ours_acc)},
        "ted_accuracy_max_difference_per_document": max(abs(x - y) for x, y in zip(donut_acc, ours_acc, strict=True)),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    same = (
        report["field_f1"]["donut"] == report["field_f1"]["vde"]
        and report["ted_accuracy_max_difference_per_document"] < 1e-9
    )
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
