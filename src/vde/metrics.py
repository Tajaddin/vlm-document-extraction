"""The scores.

Receipts (CORD) use the two metrics Donut introduced, with the same semantics as its `JSONParseEvaluator`
(github.com/clovaai/donut, MIT): field-level F1 over flattened (key path, value) pairs, where a wrong value counts as
one false positive and one false negative, and normalised tree-edit-distance accuracy, 1 - TED(pred, gold) /
TED(empty, gold), floored at 0. Values are compared exactly as printed, because that is what the benchmark asks.

Invoices (FATURA) compare each schema field after normalisation (amounts as decimals, dates as ISO, names
case-folded), so "1,146.46" and 1146.46 are the same total."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from vde import normalize
from vde.ted import Node, distance, levenshtein

# --- receipts: Donut's normalisation, F1 and TED accuracy ---------------------------------------------------------


def normalize_tree(data: Any) -> Any:
    """Donut's `normalize_dict`: keys sorted by (length, name), empty values dropped, every leaf a list of stripped
    strings, lists of dicts kept as lists."""
    if not data:
        return {}
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key in sorted(data, key=lambda k: (len(k), k)):
            value = normalize_tree(data[key])
            if value:
                out[key] = value if isinstance(value, list) else [value]
        return out
    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return [n for item in data if (n := normalize_tree(item))]
        return [str(item).strip() for item in data if isinstance(item, str | int | float) and str(item).strip()]
    return [str(data).strip()]


def flatten(data: Any, key: str = "") -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for child, value in data.items():
            pairs += flatten(value, f"{key}.{child}" if key else child)
    elif isinstance(data, list):
        for item in data:
            pairs += flatten(item, key)
    else:
        pairs.append((key, data))
    return pairs


@dataclass(frozen=True)
class Counts:
    tp: int
    fp: int
    fn: int

    @property
    def f1(self) -> float:
        denominator = self.tp + (self.fp + self.fn) / 2
        return self.tp / denominator if denominator else 1.0


def field_counts(pred: Any, gold: Any) -> Counts:
    """True positives, false positives and false negatives of one document, as Donut counts them."""
    answer = flatten(normalize_tree(gold))
    tp = fp = 0
    for pair in flatten(normalize_tree(pred)):
        if pair in answer:
            tp += 1
            answer.remove(pair)
        else:
            fp += 1
    return Counts(tp, fp, len(answer))


def _tree(data: Any, label: str = "<root>") -> Node:
    node = Node(label)
    if isinstance(data, dict):
        for key, value in data.items():
            node.add(_tree(value, key))
    elif isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            for item in data:
                node.add(_tree(item, "<subtree>"))
        else:
            for item in data:
                node.add(Node(f"<leaf>{item}"))
    else:
        raise TypeError(f"unexpected value under {label}: {data!r}")
    return node


def _leaf(node: Node) -> str | None:
    return node.label[len("<leaf>") :] if node.label.startswith("<leaf>") else None


def _insert_or_remove(node: Node) -> float:
    leaf = _leaf(node)
    return float(len(leaf)) if leaf is not None else 1.0


def _update(a: Node, b: Node) -> float:
    la, lb = _leaf(a), _leaf(b)
    if la is not None and lb is not None:
        return float(levenshtein(la, lb))
    if la is None and lb is not None:
        return 1.0 + len(lb)
    if la is not None and lb is None:
        return 1.0 + len(la)
    return float(a.label != b.label)


def ted_accuracy(pred: Any, gold: Any) -> float:
    gold_tree = _tree(normalize_tree(gold))
    worst = distance(_tree(normalize_tree({})), gold_tree, _insert_or_remove, _insert_or_remove, _update)
    if worst == 0:
        return 1.0 if not normalize_tree(pred) else 0.0
    d = distance(_tree(normalize_tree(pred)), gold_tree, _insert_or_remove, _insert_or_remove, _update)
    return max(0.0, 1.0 - d / worst)


# --- invoices: per-field comparison after normalisation ------------------------------------------------------------

Normalizer = Callable[[object], Any]


def _email(value: object) -> str | None:
    t = normalize.text(value)
    return t.replace(" ", "") if t else None


INVOICE_FIELDS: dict[str, Normalizer] = {
    "invoice_number": normalize.identifier,
    "invoice_date": normalize.iso_date,
    "due_date": normalize.iso_date,
    "po_number": normalize.identifier,
    "seller_name": normalize.text,
    "seller_email": _email,
    "buyer_name": normalize.text,
    "currency": normalize.currency,
    "subtotal": normalize.amount,
    "tax": normalize.amount,
    "discount": normalize.amount,
    "total": normalize.amount,
}


def invoice_outcomes(pred: dict[str, Any] | None, gold: dict[str, Any]) -> dict[str, str]:
    """Per field: correct, wrong (both present, different), missed (gold present, prediction empty), spurious
    (prediction present where the invoice prints nothing) or absent (neither)."""
    pred = pred or {}
    out = {}
    for name, norm in INVOICE_FIELDS.items():
        g, p = norm(gold.get(name)), norm(pred.get(name))
        if g is None:
            out[name] = "absent" if p is None else "spurious"
        elif p is None:
            out[name] = "missed"
        else:
            out[name] = "correct" if p == g else "wrong"
    return out


def invoice_counts(outcomes: dict[str, str]) -> Counts:
    """Pair counts in Donut's style: a wrong value is one false positive and one false negative."""
    values = list(outcomes.values())
    tp = values.count("correct")
    fp = values.count("wrong") + values.count("spurious")
    fn = values.count("wrong") + values.count("missed")
    return Counts(tp, fp, fn)


# --- aggregation -----------------------------------------------------------------------------------------------------


def micro_f1(counts: Sequence[Counts]) -> float:
    return Counts(sum(c.tp for c in counts), sum(c.fp for c in counts), sum(c.fn for c in counts)).f1


def bootstrap(
    values: Sequence[Any], statistic: Callable[[Sequence[Any]], float], n: int = 2000, seed: int = 0
) -> tuple[float, float]:
    """A 95% percentile interval for a statistic of per-document values, resampling documents."""
    if not values:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n, len(values)))
    stats = np.array([statistic([values[i] for i in row]) for row in idx])
    low, high = np.percentile(stats, [2.5, 97.5])
    return (round(float(low), 4), round(float(high), 4))


def mean(values: Sequence[float]) -> float:
    return float(np.mean(values)) if values else float("nan")
