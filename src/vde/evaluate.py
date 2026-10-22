"""Run an extractor over a document set and score it.

Predictions go to a JSONL file one document at a time, so a long run can stop and resume; the report is computed from
that file and records everything needed to reproduce the number (model, prompt version, schema variant, examples,
documents, hardware). Latency percentiles leave out the first document, which includes loading the model."""

from __future__ import annotations

import json
import platform
import subprocess
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from vde import checks, log
from vde.documents import Document
from vde.extract import prompts
from vde.extract.base import Extractor
from vde.metrics import (
    INVOICE_FIELDS,
    Counts,
    bootstrap,
    field_counts,
    invoice_counts,
    invoice_outcomes,
    micro_f1,
    ted_accuracy,
)

logger = log.get(__name__)


def run(extractor: Extractor, docs: Sequence[Document], predictions: Path) -> list[dict[str, Any]]:
    """Extract every document not already in `predictions`, appending as it goes; returns all rows in doc order."""
    done: dict[str, dict[str, Any]] = {}
    if predictions.is_file():
        for line in predictions.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["id"]] = row
    predictions.parent.mkdir(parents=True, exist_ok=True)
    with predictions.open("a", encoding="utf-8", newline="\n") as out:
        for i, doc in enumerate(docs):
            if doc.id in done:
                continue
            result = extractor.extract(doc)
            row = {"id": doc.id, "order": i, **result.as_dict()}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            done[doc.id] = row
            logger.info(
                "extracted", doc=doc.id, seconds=round(result.seconds, 2), error=result.error, n=i + 1, of=len(docs)
            )
    return [done[d.id] for d in docs]


def _pct(values: Sequence[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 3) if values else None


def _latency(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: r.get("order", 0))
    warm = [r["seconds"] for r in ordered[1:]]
    out: dict[str, Any] = {
        "first_document_s": ordered[0]["seconds"] if ordered else None,
        "p50_s": _pct(warm, 50),
        "p95_s": _pct(warm, 95),
        "mean_s": round(float(np.mean(warm)), 3) if warm else None,
    }
    stages: dict[str, list[float]] = {}
    for r in ordered[1:]:
        for name, seconds in (r.get("stages") or {}).items():
            stages.setdefault(name, []).append(seconds)
    if stages:
        out["stage_p50_s"] = {name: _pct(v, 50) for name, v in stages.items()}
    tokens = [r["prompt_tokens"] for r in rows if r.get("prompt_tokens")]
    if tokens:
        out["prompt_tokens_mean"] = round(float(np.mean(tokens)), 1)
        out["completion_tokens_mean"] = round(float(np.mean([r["completion_tokens"] or 0 for r in rows])), 1)
    return out


def score_receipts(docs: Sequence[Document], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    per_doc = []
    for doc, row in zip(docs, rows, strict=True):
        counts = field_counts(row["fields"], doc.gold)
        per_doc.append(
            {
                "id": doc.id,
                "tp": counts.tp,
                "fp": counts.fp,
                "fn": counts.fn,
                "ted_accuracy": round(ted_accuracy(row["fields"] or {}, doc.gold), 4),
                "seconds": row["seconds"],
                "error": row["error"],
            }
        )
    counts_list = [Counts(d["tp"], d["fp"], d["fn"]) for d in per_doc]
    teds = [d["ted_accuracy"] for d in per_doc]
    return {
        "documents": len(per_doc),
        "field_f1": round(micro_f1(counts_list), 4),
        "field_f1_95ci": bootstrap(counts_list, micro_f1),
        "ted_accuracy": round(float(np.mean(teds)), 4),
        "ted_accuracy_95ci": bootstrap(teds, lambda v: float(np.mean(v))),
        "errors": dict(Counter(r["error"] for r in rows if r["error"])),
        "latency": _latency(rows),
        "per_document": per_doc,
    }


def score_invoices(docs: Sequence[Document], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    per_doc = []
    by_field: dict[str, Counter[str]] = {name: Counter() for name in INVOICE_FIELDS}
    by_layout: dict[int, list[Counts]] = {}
    for doc, row in zip(docs, rows, strict=True):
        outcomes = invoice_outcomes(row["fields"], doc.gold or {})
        counts = invoice_counts(outcomes)
        for name, outcome in outcomes.items():
            by_field[name][outcome] += 1
        by_layout.setdefault(int(doc.meta["layout"]), []).append(counts)
        per_doc.append(
            {
                "id": doc.id,
                "layout": doc.meta["layout"],
                "outcomes": outcomes,
                "tp": counts.tp,
                "fp": counts.fp,
                "fn": counts.fn,
                "all_correct": all(o in ("correct", "absent") for o in outcomes.values()),
                "seconds": row["seconds"],
                "error": row["error"],
            }
        )
    counts_list = [Counts(d["tp"], d["fp"], d["fn"]) for d in per_doc]
    fields = {}
    for name, c in by_field.items():
        printed = c["correct"] + c["wrong"] + c["missed"]
        fields[name] = {
            "printed": printed,
            "accuracy": round(c["correct"] / printed, 4) if printed else None,
            "wrong": c["wrong"],
            "missed": c["missed"],
            "spurious": c["spurious"],
        }
    exact = [1.0 if d["all_correct"] else 0.0 for d in per_doc]
    return {
        "documents": len(per_doc),
        "field_f1": round(micro_f1(counts_list), 4),
        "field_f1_95ci": bootstrap(counts_list, micro_f1),
        "documents_fully_correct": round(float(np.mean(exact)), 4),
        "documents_fully_correct_95ci": bootstrap(exact, lambda v: float(np.mean(v))),
        "fields": fields,
        "field_f1_by_layout": {str(k): round(micro_f1(v), 4) for k, v in sorted(by_layout.items())},
        "errors": dict(Counter(r["error"] for r in rows if r["error"])),
        "latency": _latency(rows),
        "per_document": per_doc,
    }


def environment(ollama_url: str | None) -> dict[str, Any]:
    env: dict[str, Any] = {
        "python": platform.python_version(),
        "os": platform.platform(terse=True),
        "cpu": platform.processor(),
    }
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        env["gpu"] = gpu.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        env["gpu"] = None
    if ollama_url:
        try:
            env["ollama"] = httpx.get(f"{ollama_url}/api/version", timeout=5).json().get("version")
        except (httpx.HTTPError, ValueError):
            env["ollama"] = None
    return env


def review(
    docs: Sequence[Document], rows: Sequence[dict[str, Any]], per_doc: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Do the review flags (vde.checks) catch the wrong extractions? A document's extraction is wrong when any field
    is wrong, missed or invented. The same flags run on the gold labels show how often they fire on correct data."""
    table: Counter[str] = Counter()
    by_flag: dict[str, Counter[str]] = {}
    gold_flagged: Counter[str] = Counter()
    for doc, row, scored in zip(docs, rows, per_doc, strict=True):
        wrong = scored["fp"] + scored["fn"] > 0
        raised = checks.flags(doc.kind, row["fields"])
        table[("flagged" if raised else "passed") + ("_wrong" if wrong else "_right")] += 1
        for flag in raised:
            by_flag.setdefault(flag, Counter())["wrong" if wrong else "right"] += 1
        for flag in checks.flags(doc.kind, doc.gold):
            gold_flagged[flag] += 1
    wrong_total = table["flagged_wrong"] + table["passed_wrong"]
    flagged_total = table["flagged_wrong"] + table["flagged_right"]
    return {
        "documents_wrong": wrong_total,
        "documents_flagged": flagged_total,
        "wrong_caught": round(table["flagged_wrong"] / wrong_total, 4) if wrong_total else None,
        "flagged_that_were_wrong": round(table["flagged_wrong"] / flagged_total, 4) if flagged_total else None,
        "table": dict(table),
        "by_flag": {k: dict(v) for k, v in sorted(by_flag.items())},
        "flags_on_gold_labels": dict(gold_flagged),
    }


def report(
    name: str,
    docs: Sequence[Document],
    rows: Sequence[dict[str, Any]],
    config: dict[str, Any],
    examples: Iterable[Document] = (),
) -> dict[str, Any]:
    kind = docs[0].kind
    scores = score_receipts(docs, rows) if kind == "receipt" else score_invoices(docs, rows)
    return {
        "run": name,
        "kind": kind,
        "prompt_version": prompts.VERSION,
        "config": config,
        "examples": [e.id for e in examples],
        "document_ids": [d.id for d in docs],
        **scores,
        "review": review(docs, rows, scores["per_document"]),
    }
