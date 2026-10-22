"""FATURA v2 invoices, read straight from the published zip.

The held-out test uses the authors' layout split (`Strat2_Split.txt`): 40 training layouts and 10 test layouts, so a
model is scored on layouts it has never been shown, and few-shot examples come only from the training layouts.

The annotations give each field as the text printed on the page, label included ("TOTAL : 575.33 EUR"); `gold_fields`
turns that into the invoice schema's values, and `parse_report` says how often each field parsed."""

from __future__ import annotations

import ast
import json
import random
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from vde import normalize
from vde.documents import Document

ROOT = "invoices_dataset_final"
NAME = re.compile(r"Template(\d+)_Instance(\d+)\.json$")
Split = Literal["train", "test"]

_NUMBER_LABEL = re.compile(r"^\s*(invoice\s*(number|no\.?|id|#)|inv\s*id)\s*[:#]?\s*", re.IGNORECASE)
_PO_LABEL = re.compile(r"^\s*p\.?\s*o\.?\s*(number|no\.?|#)?\s*[:#]?\s*", re.IGNORECASE)
_BUYER_LABEL = re.compile(r"^\s*(bill(ed)?[\s_]*to|buyer)\s*:?\s*", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")

FIELDS = (
    "invoice_number",
    "invoice_date",
    "due_date",
    "po_number",
    "seller_name",
    "seller_email",
    "buyer_name",
    "currency",
    "subtotal",
    "tax",
    "discount",
    "total",
)


def _text(annotation: dict[str, Any], key: str) -> str | None:
    value = annotation.get(key)
    if isinstance(value, dict) and isinstance(value.get("text"), str) and value["text"].strip():
        return str(value["text"])
    return None


def _buyer(raw: str) -> str | None:
    lines = [line.strip() for line in _BUYER_LABEL.sub("", raw.strip(), count=1).splitlines() if line.strip()]
    return lines[0] if lines else None


def gold_fields(annotation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """The invoice schema's gold values (None when the invoice does not print the field), and for every field that
    is printed but would not parse, the raw text, so the data-quality report can list it."""
    raw = {
        "invoice_number": _text(annotation, "NUMBER"),
        "invoice_date": _text(annotation, "DATE"),
        "due_date": _text(annotation, "DUE_DATE"),
        "po_number": _text(annotation, "PO_NUMBER"),
        "seller_name": _text(annotation, "SELLER_NAME"),
        "seller_email": _text(annotation, "SELLER_EMAIL"),
        "buyer_name": _text(annotation, "BUYER") or _text(annotation, "BILL_TO"),
        "currency": _text(annotation, "TOTAL") or _text(annotation, "AMOUNT_DUE") or _text(annotation, "SUB_TOTAL"),
        "subtotal": _text(annotation, "SUB_TOTAL"),
        "tax": _text(annotation, "TAX"),
        "discount": _text(annotation, "DISCOUNT"),
        # some layouts file the amount due under AMOUNT_DUE ("BALANCE_DUE : ..."), others under TOTAL
        "total": _text(annotation, "TOTAL") or _text(annotation, "AMOUNT_DUE"),
    }
    parsed: dict[str, Any] = {}
    failed: dict[str, str] = {}
    for name, text in raw.items():
        if text is None:
            parsed[name] = None
            continue
        value: Any
        if name == "invoice_number":
            value = normalize.identifier(_NUMBER_LABEL.sub("", text, count=1))
        elif name == "po_number":
            value = normalize.identifier(_PO_LABEL.sub("", text, count=1))
        elif name in ("invoice_date", "due_date"):
            value = normalize.iso_date(text)
        elif name == "seller_email":
            match = _EMAIL.search(text)
            value = match.group(0).lower() if match else None
        elif name == "buyer_name":
            value = _buyer(text)
        elif name == "currency":
            value = normalize.currency(text)
        elif name == "seller_name":
            value = text.strip()
        else:
            amount = normalize.amount(text)
            value = str(amount) if amount is not None else None
        parsed[name] = value
        if value is None and name != "currency":  # a total printed without a currency symbol prints no currency
            failed[name] = text
    return parsed, failed


class Fatura:
    """The zip, opened once; images and annotations are read on demand."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "raw" / "fatura" / "FATURA2.zip"
        if not self.path.is_file():
            raise FileNotFoundError(f"{self.path}: run `vde fetch` first")
        self.zip = zipfile.ZipFile(self.path)
        self.instances: dict[int, list[int]] = defaultdict(list)
        for name in self.zip.namelist():
            if "/Original_Format/" in name and (m := NAME.search(name)):
                self.instances[int(m.group(1))].append(int(m.group(2)))
        for ids in self.instances.values():
            ids.sort()
        # the authors' layout split
        text = self.zip.read(f"{ROOT}/Strat2_Split.txt").decode("utf-8")
        values = dict(re.findall(r"(\w+)\s*=\s*(\[[^\]]*\])", text))
        test = values.get("test_inds") or values["dev_inds"]  # the file says `test_inds = dev_inds`
        self.layouts: dict[str, list[int]] = {
            "train": sorted(ast.literal_eval(values["train_inds"])),
            "test": sorted(ast.literal_eval(test)),
        }

    def annotation(self, template: int, instance: int) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(
            self.zip.read(f"{ROOT}/Annotations/Original_Format/Template{template}_Instance{instance}.json")
        )
        return data

    def document(self, template: int, instance: int, split: str) -> Document:
        gold, failed = gold_fields(self.annotation(template, instance))
        return Document(
            id=f"fatura-t{template}-i{instance}",
            kind="invoice",
            image=self.zip.read(f"{ROOT}/images/Template{template}_Instance{instance}.jpg"),
            gold=gold,
            meta={"dataset": "fatura", "split": split, "layout": template, "instance": instance, "unparsed": failed},
        )

    def sample(self, split: Split, per_layout: int, seed: int) -> list[Document]:
        """`per_layout` instances from every layout of the split, chosen with a fixed seed."""
        rng = random.Random(seed)
        docs = []
        for template in self.layouts[split]:
            for instance in sorted(rng.sample(self.instances[template], per_layout)):
                docs.append(self.document(template, instance, split))
        return docs


def parse_report(fatura: Fatura) -> dict[str, Any]:
    """Over every annotation in the dataset: per field, how many invoices print it and how many of those parsed."""
    printed: Counter[str] = Counter()
    parsed: Counter[str] = Counter()
    failures: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total = 0
    for template, instances in sorted(fatura.instances.items()):
        for instance in instances:
            total += 1
            gold, failed = gold_fields(fatura.annotation(template, instance))
            for name in FIELDS:
                if gold[name] is not None or name in failed:
                    printed[name] += 1
                if gold[name] is not None:
                    parsed[name] += 1
            for name, text in failed.items():
                failures[name].append({"layout": template, "instance": instance, "text": text})
    return {
        "invoices": total,
        "fields": {
            name: {
                "printed": printed[name],
                "parsed": parsed[name],
                "parse_rate": round(parsed[name] / printed[name], 4) if printed[name] else None,
            }
            for name in FIELDS
        },
        "failures": {name: rows[:50] for name, rows in failures.items()},
        "failure_counts": {name: len(rows) for name, rows in failures.items()},
    }
