"""Review flags: cheap rules that mark an extraction for a person to look at before anything is paid.

They never change a value. Whether they are worth having is measured (`vde review-eval`): how many wrong extractions
they catch, and how often they fire on correct ones, including on the gold labels themselves (a receipt whose own
printed numbers do not add up would be flagged however good the model is)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from vde import normalize

# CORD receipts print Indonesian rupiah: "16,500", "60.000" and "-60.000" are whole amounts; the separator groups
# thousands. A tolerance of 1% absorbs rounding on the few receipts with cents.
_TOLERANCE = 0.01


def rupiah(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
        if value is None:
            return None
    digits = re.sub(r"[^\d]", "", str(value))
    if not digits:
        return None
    return -int(digits) if str(value).strip().startswith("-") else int(digits)


def _close(a: int | float, b: int | float) -> bool:
    return abs(a - b) <= max(1.0, _TOLERANCE * max(abs(a), abs(b)))


def _menu(fields: dict[str, Any]) -> list[dict[str, Any]]:
    menu = fields.get("menu")
    if isinstance(menu, dict):
        return [menu]
    return [m for m in menu or [] if isinstance(m, dict)]


def _group(fields: dict[str, Any], key: str) -> dict[str, Any]:
    value = fields.get(key)
    return value if isinstance(value, dict) else {}


def receipt_flags(fields: dict[str, Any] | None) -> list[str]:
    if not fields:
        return ["no_result"]
    flags = []
    total, sub = _group(fields, "total"), _group(fields, "sub_total")
    total_price = rupiah(total.get("total_price"))
    if total_price is None:
        flags.append("no_total")
    prices = [rupiah(m.get("price")) for m in _menu(fields)]
    items = sum(p for p in prices if p is not None) if prices and all(p is not None for p in prices) else None
    subtotal = rupiah(sub.get("subtotal_price"))
    if items is not None and subtotal is not None and not _close(items, subtotal):
        flags.append("items_do_not_sum_to_subtotal")
    elif (
        items is not None
        and subtotal is None
        and total_price is not None
        and not sub
        and not _close(items, total_price)
    ):
        flags.append("items_do_not_sum_to_total")
    cash, change = rupiah(total.get("cashprice")), rupiah(total.get("changeprice"))
    if total_price is not None and cash is not None and change is not None and not _close(cash - total_price, change):
        flags.append("change_does_not_match")
    return flags


def invoice_flags(fields: dict[str, Any] | None) -> list[str]:
    if not fields:
        return ["no_result"]
    flags = []
    total = normalize.amount(fields.get("total"))
    if total is None:
        flags.append("no_total")
    elif total <= 0:
        flags.append("total_not_positive")
    for name in ("invoice_date", "due_date"):
        if fields.get(name) is not None and normalize.iso_date(fields.get(name)) is None:
            flags.append(f"{name}_unreadable")
    issued, due = normalize.iso_date(fields.get("invoice_date")), normalize.iso_date(fields.get("due_date"))
    if issued and due and date.fromisoformat(due) < date.fromisoformat(issued):
        flags.append("due_before_issue")
    if fields.get("currency") is not None and normalize.currency(fields.get("currency")) is None:
        flags.append("unknown_currency")
    if not fields.get("invoice_number"):
        flags.append("no_invoice_number")
    subtotal, tax, discount = (normalize.amount(fields.get(k)) for k in ("subtotal", "tax", "discount"))
    if total is not None and subtotal is not None and total < subtotal - (discount or 0):
        flags.append("total_below_subtotal")
    if tax is not None and subtotal is not None and tax > subtotal:
        flags.append("tax_above_subtotal")
    return flags


def flags(kind: str, fields: dict[str, Any] | None) -> list[str]:
    return receipt_flags(fields) if kind == "receipt" else invoice_flags(fields)
