"""The JSON schemas the models must answer in (Ollama turns them into a grammar, so the output always parses).

Receipts follow CORD's own key set (Donut's `gt_parse`), inventoried from the validation and test labels. Two
variants exist because the spike found that constrained decoding skips optional keys: in `required`, the common keys
must be present and may be null, which makes the model decide on each one; `optional` lets it leave keys out. The
variant was chosen on the validation split (reports/dev/), never on test."""

from __future__ import annotations

from typing import Any, Literal

ReceiptVariant = Literal["optional", "required"]

STRING = {"type": "string"}
NULLABLE = {"type": ["string", "null"]}

MENU_COMMON = ("nm", "cnt", "price", "unitprice")
MENU_RARE = ("num", "discountprice", "itemsubtotal", "vatyn", "etc")
SUB_COMMON = ("subtotal_price", "tax_price", "service_price", "discount_price")
SUB_RARE = ("othersvc_price", "etc")
TOTAL_COMMON = ("total_price", "cashprice", "changeprice", "creditcardprice", "menuqty_cnt")
TOTAL_RARE = ("total_etc", "emoneyprice", "menutype_cnt")

RECEIPT_KEYS = {
    "menu": MENU_COMMON + MENU_RARE + ("sub",),
    "sub_total": SUB_COMMON + SUB_RARE,
    "total": TOTAL_COMMON + TOTAL_RARE,
}


def _group(common: tuple[str, ...], rare: tuple[str, ...], variant: ReceiptVariant) -> dict[str, Any]:
    if variant == "required":
        props = dict.fromkeys(common, NULLABLE) | dict.fromkeys(rare, STRING)
        return {"type": "object", "properties": props, "required": list(common)}
    return {"type": "object", "properties": dict.fromkeys(common + rare, STRING)}


def receipt_schema(variant: ReceiptVariant = "required") -> dict[str, Any]:
    item = _group(MENU_COMMON, MENU_RARE, variant)
    sub_item = {
        "type": "object",
        "properties": dict.fromkeys(("nm", "unitprice", "cnt", "price", "discountprice", "etc"), STRING),
    }
    item["properties"]["sub"] = {"type": "array", "items": sub_item}
    return {
        "type": "object",
        "properties": {
            "menu": {"type": "array", "items": item},
            "sub_total": _group(SUB_COMMON, SUB_RARE, variant),
            "total": _group(TOTAL_COMMON, TOTAL_RARE, variant),
        },
        "required": ["menu", "sub_total", "total"] if variant == "required" else ["menu", "total"],
    }


INVOICE_STRINGS = (
    "invoice_number",
    "invoice_date",
    "due_date",
    "po_number",
    "seller_name",
    "seller_email",
    "buyer_name",
    "currency",
)
INVOICE_AMOUNTS = ("subtotal", "tax", "discount", "total")


def invoice_schema() -> dict[str, Any]:
    props: dict[str, Any] = {k: {"type": ["string", "null"]} for k in INVOICE_STRINGS}
    props |= {k: {"type": ["number", "null"]} for k in INVOICE_AMOUNTS}
    return {"type": "object", "properties": props, "required": list(INVOICE_STRINGS + INVOICE_AMOUNTS)}


def schema_for(kind: str, variant: ReceiptVariant = "required") -> dict[str, Any]:
    return receipt_schema(variant) if kind == "receipt" else invoice_schema()


def as_example(kind: str, gold: dict[str, Any]) -> dict[str, Any]:
    """Gold labels in the shape the schema asks for, to show the model as a worked example."""
    if kind == "receipt":
        out = dict(gold)
        if isinstance(out.get("menu"), dict):
            out["menu"] = [out["menu"]]
        out.setdefault("menu", [])
        out.setdefault("sub_total", {})
        out.setdefault("total", {})
        return out
    example: dict[str, Any] = {}
    for key in INVOICE_STRINGS + INVOICE_AMOUNTS:
        value = gold.get(key)
        example[key] = float(value) if key in INVOICE_AMOUNTS and value is not None else value
    return example
