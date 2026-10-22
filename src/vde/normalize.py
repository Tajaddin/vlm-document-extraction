"""Normalising extracted values before they are compared: the same amount, date or name written two ways must count
as the same value, and anything that cannot be parsed stays as text so it can still be compared exactly."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"-?\d[\d,.\s]*")
_DATE_FORMATS = (
    "%d-%b-%Y",  # 25-Aug-1997 (FATURA's usual form)
    "%d-%B-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)
CURRENCIES = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "INR": "INR",
    "₹": "INR",
}


def amount(value: object) -> Decimal | None:
    """The last number in the text as a Decimal with two places: '1,146.46 EUR' -> 1146.46, '(-)  7.81' -> 7.81.
    A comma followed by exactly two digits at the end is a decimal comma ('12,50'); otherwise commas group thousands."""
    if value is None:
        return None
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        return abs(Decimal(str(value))).quantize(Decimal("0.01"))
    matches = _NUMBER.findall(str(value))
    if not matches:
        return None
    raw = re.sub(r"\s", "", matches[-1]).rstrip(".,")
    if re.search(r",\d{2}$", raw) and "." not in raw:
        raw = raw.replace(",", ".")
    raw = raw.replace(",", "")
    if raw.count(".") > 1:  # 1.234.567 grouping with dots
        raw = raw.replace(".", "")
    try:
        return abs(Decimal(raw)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def iso_date(value: object) -> str | None:
    """A date in any of the common printed forms as YYYY-MM-DD; None when it is not a date."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = re.sub(r"\s+", " ", str(value)).strip().rstrip(".")
    candidates = [text, *re.findall(r"\d{1,4}[-/. ][A-Za-z]{3,9}[-/. ]\d{2,4}|\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}", text)]
    for candidate in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate.strip(), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def currency(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for token in sorted(CURRENCIES, key=len, reverse=True):
        if token in text.upper() or token in text:
            return CURRENCIES[token]
    return None


def text(value: object) -> str | None:
    """Case-folded, whitespace collapsed, surrounding punctuation dropped; None for empty values."""
    if value is None:
        return None
    out = re.sub(r"\s+", " ", str(value)).strip().strip(".,;:|-").strip()
    return out.casefold() or None


def identifier(value: object) -> str | None:
    """Invoice and PO numbers: upper case, no spaces."""
    t = text(value)
    return re.sub(r"\s", "", t).upper() if t else None
