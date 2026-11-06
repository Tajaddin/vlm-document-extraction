"""The paired comparisons in scripts/analyze_eval.py: a failed document counts against the run that failed it, as it
does in each report's headline F1."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def analyze() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analyze_eval", ROOT / "scripts" / "analyze_eval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def doc(i: str, tp: int, fn: int, error: str | None = None) -> dict[str, object]:
    return {"id": i, "tp": tp, "fp": 0, "fn": fn, "error": error}


def test_a_failed_document_is_an_empty_answer_and_answered_only_is_reported_apart(analyze: ModuleType) -> None:
    a = {"per_document": [doc("1", 5, 0), doc("2", 5, 0)]}
    b = {"per_document": [doc("1", 5, 0), doc("2", 0, 5, error="ollama 400: context")]}
    result = analyze.paired(a, b, n=50)
    assert (result["documents"], result["failed_a"], result["failed_b"]) == (2, 0, 1)
    assert (result["f1_a"], result["f1_b"], result["difference"]) == (1.0, 0.6667, -0.3333)
    assert result["significant"] is False  # two documents
    answered = result["answered_by_both"]
    assert (answered["documents"], answered["difference"]) == (1, 0.0)


@pytest.mark.parametrize("dataset", ["cord", "fatura"])
def test_the_paired_f1s_are_the_headline_f1s_of_the_committed_runs(analyze: ModuleType, dataset: str) -> None:
    reports = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (ROOT / "reports/eval" / f"{dataset}-test").glob("*.json")
    }
    baseline = reports["ocr-qwen2.5-7b-0shot" + ("-required" if dataset == "cord" else "")]
    for run, report in reports.items():
        result = analyze.paired(baseline, report, n=10)
        assert (result["f1_a"], result["f1_b"]) == (baseline["field_f1"], report["field_f1"]), run
