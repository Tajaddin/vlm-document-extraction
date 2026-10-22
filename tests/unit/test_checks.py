import pytest

from vde.checks import flags, invoice_flags, receipt_flags, rupiah

RECEIPT = {
    "menu": [
        {"nm": "REAL GANACHE", "price": "16,500"},
        {"nm": "EGG TART", "price": "13,000"},
        {"nm": "PIZZA TOAST", "price": "16,000"},
    ],
    "total": {"total_price": "45,500", "cashprice": "50,000", "changeprice": "4,500"},
}


@pytest.mark.parametrize(
    ("raw", "want"),
    [("16,500", 16500), ("60.000", 60000), ("-60.000", -60000), (["5.455"], 5455), ("Rp", None), (None, None)],
)
def test_rupiah(raw: object, want: int | None) -> None:
    assert rupiah(raw) == want


def test_a_consistent_receipt_has_no_flags() -> None:
    assert receipt_flags(RECEIPT) == []
    assert receipt_flags({**RECEIPT, "menu": {"nm": "ONE", "price": "45,500"}}) == []  # a one-item menu as a dict


def test_receipt_flags() -> None:
    wrong_item = {**RECEIPT, "menu": [*RECEIPT["menu"][:2], {"nm": "PIZZA TOAST", "price": "18,000"}]}
    assert receipt_flags(wrong_item) == ["items_do_not_sum_to_total"]
    assert receipt_flags(
        {**RECEIPT, "total": {"total_price": "45,500", "cashprice": "50,000", "changeprice": "5,500"}}
    ) == ["change_does_not_match"]
    assert receipt_flags({"menu": RECEIPT["menu"], "sub_total": {"subtotal_price": "40,000"}, "total": {}}) == [
        "no_total",
        "items_do_not_sum_to_subtotal",
    ]
    assert receipt_flags(None) == ["no_result"]


def test_invoice_flags() -> None:
    good = {
        "invoice_number": "INV1",
        "invoice_date": "2021-04-21",
        "due_date": "2021-05-21",
        "currency": "EUR",
        "subtotal": 561.52,
        "tax": 29.48,
        "discount": 7.81,
        "total": 575.33,
    }
    assert invoice_flags(good) == []
    assert invoice_flags({**good, "due_date": "2020-09-27"}) == ["due_before_issue"]
    assert invoice_flags({**good, "total": None, "invoice_number": None}) == ["no_total", "no_invoice_number"]
    assert invoice_flags({**good, "invoice_date": "sometime", "currency": "doubloons"}) == [
        "invoice_date_unreadable",
        "unknown_currency",
    ]
    assert invoice_flags({**good, "total": 100, "tax": 600}) == ["total_below_subtotal", "tax_above_subtotal"]
    assert flags("invoice", {**good, "total": 0}) == ["total_not_positive", "total_below_subtotal"]
