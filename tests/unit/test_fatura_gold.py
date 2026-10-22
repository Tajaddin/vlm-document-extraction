"""The gold parser on annotation strings copied from FATURA v2 (Template1_Instance1 and others)."""

from vde.data.fatura import gold_fields

ANNOTATION = {
    "BUYER": {"text": "Bill to:Sherri Morgan\n2927 Ana Unions\nRobertbury, MD 41620 US\nTel:+(588)629-8002"},
    "DATE": {"text": "Date: 21-Apr-2021"},
    "DISCOUNT": {"text": "DISCOUNT(1.39%): (-)  7.81"},
    "DUE_DATE": {"text": "Due Date : 27-Sep-2020"},
    "PO_NUMBER": {"text": "PO Number :76"},
    "SELLER_EMAIL": {"text": "Email:melvin40@example.net"},
    "SUB_TOTAL": {"text": "SUB_TOTAL : 561.52  EUR"},
    "TAX": {"text": "TAX:VAT (5.25%):  29.48 EUR"},
    "TOTAL": {"text": "TOTAL : 575.33 EUR"},
    "NUMBER": {"text": "INVOICE # 8Y2M5d-503"},
    "SELLER_NAME": {"text": "Kelly-Moss"},
    "TABLE": [[{"bbox": [[10.0, 310.9], [560.0, 220.9]]}]],
    "OTHER": {"text": "COMMERCIAL INVOICE ..."},
}


def test_every_field_parses() -> None:
    gold, failed = gold_fields(ANNOTATION)
    assert failed == {}
    assert gold == {
        "invoice_number": "8Y2M5D-503",
        "invoice_date": "2021-04-21",
        "due_date": "2020-09-27",
        "po_number": "76",
        "seller_name": "Kelly-Moss",
        "seller_email": "melvin40@example.net",
        "buyer_name": "Sherri Morgan",
        "currency": "EUR",
        "subtotal": "561.52",
        "tax": "29.48",
        "discount": "7.81",
        "total": "575.33",
    }


def test_fields_the_invoice_does_not_print_are_none() -> None:
    gold, failed = gold_fields({"DATE": {"text": "Invoice Date: 10-Jul-2008"}})
    assert gold["invoice_date"] == "2008-07-10"
    assert gold["total"] is None and gold["buyer_name"] is None
    assert failed == {}


def test_other_label_forms() -> None:
    gold, _ = gold_fields(
        {
            "NUMBER": {"text": "INVOICE ID INV17272458"},
            "BILL_TO": {"text": "BILL_TO:\nKeith Ortiz\n811 Franklin Port Suite 241"},
            "TOTAL": {"text": "BALANCE DUE : 817.74 USD"},
        }
    )
    assert gold["invoice_number"] == "INV17272458"
    assert gold["buyer_name"] == "Keith Ortiz"
    assert gold["total"] == "817.74"
    assert gold["currency"] == "USD"


def test_unparseable_text_is_reported_not_guessed() -> None:
    gold, failed = gold_fields({"DATE": {"text": "Date: soon"}, "TOTAL": {"text": "TOTAL : see attached"}})
    assert gold["invoice_date"] is None and gold["total"] is None
    assert failed == {"invoice_date": "Date: soon", "total": "TOTAL : see attached"}


def test_amount_due_is_the_total_when_the_layout_has_no_total() -> None:
    gold, _ = gold_fields(
        {"AMOUNT_DUE": {"text": "BALANCE_DUE : 1158.86 EUR"}, "SUB_TOTAL": {"text": "SUB_TOTAL : 1100.00  EUR"}}
    )
    assert gold["total"] == "1158.86" and gold["currency"] == "EUR"
    both, _ = gold_fields({"TOTAL": {"text": "TOTAL : 300.00 USD"}, "AMOUNT_DUE": {"text": "DUE_AMOUNT : 383.94 $"}})
    assert both["total"] == "300.00"  # TOTAL wins when a layout prints both
