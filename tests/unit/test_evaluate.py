import json
from pathlib import Path

import pytest

from vde import evaluate
from vde.documents import Document
from vde.extract.base import Extraction
from vde.extract.fake import FakeExtractor

RECEIPTS = [
    Document("r1", "receipt", b"x", gold={"menu": [{"nm": "A", "price": "1"}], "total": {"total_price": "1"}}),
    Document("r2", "receipt", b"x", gold={"menu": [{"nm": "B", "price": "2"}], "total": {"total_price": "2"}}),
]
INVOICES = [
    Document("i1", "invoice", b"x", gold={"total": "10.00", "tax": "1.00"}, meta={"layout": 2}),
    Document("i2", "invoice", b"x", gold={"total": "20.00", "tax": None}, meta={"layout": 4}),
]


class Scripted:
    """Answers each document with a prepared result and a fixed duration."""

    name = "scripted"

    def __init__(self, answers: dict[str, dict[str, object] | None], seconds: float = 2.0) -> None:
        self.answers, self.seconds, self.calls = answers, seconds, 0

    def extract(self, doc: Document) -> Extraction:
        self.calls += 1
        return Extraction(self.answers[doc.id], self.name, "m", self.seconds + (10 if doc.id.endswith("1") else 0))


def test_run_appends_and_resumes(tmp_path: Path) -> None:
    out = tmp_path / "p.jsonl"
    first = Scripted({"r1": {}, "r2": {}})
    evaluate.run(first, RECEIPTS[:1], out)
    second = Scripted({"r1": {}, "r2": {}})
    rows = evaluate.run(second, RECEIPTS, out)
    assert second.calls == 1  # r1 came from the file
    assert [r["id"] for r in rows] == ["r1", "r2"]
    assert len(out.read_text().splitlines()) == 2


def test_receipt_scores(tmp_path: Path) -> None:
    rows = evaluate.run(
        Scripted({"r1": RECEIPTS[0].gold, "r2": {"menu": [{"nm": "B", "price": "9"}]}}), RECEIPTS, tmp_path / "p.jsonl"
    )
    s = evaluate.score_receipts(RECEIPTS, rows)
    # r1: 3 tp; r2: 1 tp, 1 fp, 2 fn -> 4 / (4 + 3/2)
    assert s["field_f1"] == pytest.approx(round(4 / 5.5, 4))
    assert s["per_document"][0]["ted_accuracy"] == 1.0
    assert s["latency"]["first_document_s"] == 12.0 and s["latency"]["p50_s"] == 2.0  # the first document is set apart


def test_invoice_scores_by_field_and_layout(tmp_path: Path) -> None:
    answers = {"i1": {"total": 10, "tax": 2}, "i2": {"total": "20.00", "tax": 5}}
    s = evaluate.score_invoices(INVOICES, evaluate.run(Scripted(answers), INVOICES, tmp_path / "p.jsonl"))
    assert s["fields"]["total"] == {"printed": 2, "accuracy": 1.0, "wrong": 0, "missed": 0, "spurious": 0}
    assert s["fields"]["tax"] == {"printed": 1, "accuracy": 0.0, "wrong": 1, "missed": 0, "spurious": 1}
    assert s["documents_fully_correct"] == 0.0
    assert s["field_f1_by_layout"] == {"2": pytest.approx(1 / 2), "4": pytest.approx(1 / 1.5, abs=1e-4)}


def test_report_records_the_configuration(tmp_path: Path) -> None:
    rows = evaluate.run(FakeExtractor(echo_gold=True), INVOICES, tmp_path / "p.jsonl")
    r = evaluate.report("fake", INVOICES, rows, {"model": "fake"}, examples=RECEIPTS[:1])
    assert r["field_f1"] == 1.0 and r["documents_fully_correct"] == 1.0
    assert r["examples"] == ["r1"] and r["document_ids"] == ["i1", "i2"] and r["prompt_version"]
    json.dumps(r)  # serialisable as it is written
