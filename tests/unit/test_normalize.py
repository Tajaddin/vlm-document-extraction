from decimal import Decimal

import pytest

from vde import normalize


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("TOTAL : 1,146.46 EUR", Decimal("1146.46")),
        ("DISCOUNT(1.39%): (-)  7.81", Decimal("7.81")),
        ("TAX:VAT (5.25%):  29.48 EUR", Decimal("29.48")),
        ("12,50", Decimal("12.50")),
        ("1.234.567", Decimal("1234567.00")),
        (575.33, Decimal("575.33")),
        (-7.81, Decimal("7.81")),
        ("no number here", None),
        (None, None),
    ],
)
def test_amount(raw: object, want: Decimal | None) -> None:
    assert normalize.amount(raw) == want


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Invoice Date: 25-Aug-1997", "1997-08-25"),
        ("Due Date : 07-Apr-2016", "2016-04-07"),
        ("2021-04-21", "2021-04-21"),
        ("April 21, 2021", "2021-04-21"),
        ("21 Apr 2021", "2021-04-21"),
        ("not a date", None),
        (None, None),
    ],
)
def test_iso_date(raw: object, want: str | None) -> None:
    assert normalize.iso_date(raw) == want


def test_currency_text_and_identifier() -> None:
    assert normalize.currency("TOTAL : 616.34 $") == "USD"
    assert normalize.currency("SUB_TOTAL : 390.07  EUR") == "EUR"
    assert normalize.currency("1,000") is None
    assert normalize.text("  Kelly-Moss. ") == "kelly-moss"
    assert normalize.text("   ") is None
    assert normalize.identifier("inv 3770 769") == "INV3770769"
