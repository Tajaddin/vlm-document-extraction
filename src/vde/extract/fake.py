"""A deterministic stand-in for CI and the serverless tests: it answers with a fixed, schema-shaped result (or the gold
labels, when the document carries them), so the plumbing can be tested without a GPU. It measures nothing."""

from __future__ import annotations

from typing import Any

from vde.documents import Document
from vde.extract.base import Extraction
from vde.schemas import INVOICE_AMOUNTS, INVOICE_STRINGS, as_example

FIXED: dict[str, dict[str, Any]] = {
    "receipt": {
        "menu": [{"nm": "ITEM", "cnt": "1", "price": "10,000"}],
        "sub_total": {},
        "total": {"total_price": "10,000"},
    },
    "invoice": dict.fromkeys(INVOICE_STRINGS + INVOICE_AMOUNTS) | {"total": 100.0, "currency": "USD"},
}


class FakeExtractor:
    name = "fake"

    def __init__(self, echo_gold: bool = False) -> None:
        self.echo_gold = echo_gold

    def extract(self, doc: Document) -> Extraction:
        fields = as_example(doc.kind, doc.gold) if self.echo_gold and doc.gold is not None else dict(FIXED[doc.kind])
        return Extraction(fields, self.name, "fake", 0.0)
