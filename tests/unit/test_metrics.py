import math

import pytest

from vde.metrics import (
    Counts,
    bootstrap,
    field_counts,
    invoice_counts,
    invoice_outcomes,
    micro_f1,
    normalize_tree,
    ted_accuracy,
)

GOLD = {"menu": [{"nm": "A", "price": "1"}, {"nm": "B", "price": "2"}], "total": {"total_price": "3"}}


def test_a_wrong_value_is_one_false_positive_and_one_false_negative() -> None:
    pred = {"menu": [{"nm": "A", "price": "1"}, {"nm": "B", "price": "9"}], "total": {"total_price": "3"}}
    c = field_counts(pred, GOLD)
    assert (c.tp, c.fp, c.fn) == (4, 1, 1)
    assert c.f1 == pytest.approx(4 / 5)


def test_a_one_item_menu_as_a_dict_or_a_list_scores_the_same() -> None:
    gold = {"menu": {"nm": "TICKET", "price": "60.000"}}
    assert field_counts({"menu": [{"nm": "TICKET", "price": "60.000"}]}, gold) == Counts(2, 0, 0)
    assert normalize_tree(gold) == normalize_tree({"menu": [{"nm": "TICKET", "price": "60.000"}]})


def test_empty_and_null_values_are_dropped() -> None:
    pred = {
        "menu": [{"nm": "A", "price": "1", "cnt": None}, {"nm": "B", "price": "2", "num": ""}],
        "total": {"total_price": "3", "cashprice": None},
        "sub_total": {},
    }
    assert field_counts(pred, GOLD) == Counts(5, 0, 0)


def test_missing_document_is_all_false_negatives() -> None:
    assert field_counts(None, GOLD) == Counts(0, 0, 5)
    assert Counts(0, 0, 0).f1 == 1.0


def test_ted_accuracy_by_hand() -> None:
    gold = {"total": {"total_price": "45,500"}}
    assert ted_accuracy(gold, gold) == 1.0
    assert ted_accuracy({}, gold) == 0.0
    # root -> total -> <subtree> -> total_price -> leaf: building it from nothing costs 1 + 1 + 1 + 6 = 9;
    # one character wrong costs 1
    assert ted_accuracy({"total": {"total_price": "45,600"}}, gold) == pytest.approx(1 - 1 / 9)


def test_ted_accuracy_is_floored_at_zero() -> None:
    gold = {"total": {"total_price": "1"}}
    noisy = {"menu": [{"nm": "x" * 40, "price": "y" * 40}], "sub_total": {"etc": "z" * 40}}
    assert ted_accuracy(noisy, gold) == 0.0


def test_invoice_fields_compare_after_normalisation() -> None:
    gold = {
        "total": "575.33",
        "invoice_date": "2021-04-21",
        "seller_name": "Kelly-Moss",
        "tax": None,
        "currency": "EUR",
    }
    pred = {"total": 575.33, "invoice_date": "21-Apr-2021", "seller_name": "KELLY-MOSS ", "tax": 29.48, "currency": "€"}
    out = invoice_outcomes(pred, gold)
    assert out["total"] == out["invoice_date"] == out["seller_name"] == out["currency"] == "correct"
    assert out["tax"] == "spurious"
    assert out["due_date"] == "absent"


def test_invoice_wrong_and_missed() -> None:
    gold = {"total": "575.33", "subtotal": "561.52"}
    out = invoice_outcomes({"total": "575.38"}, gold)
    assert out["total"] == "wrong"
    assert out["subtotal"] == "missed"
    assert invoice_counts(out) == Counts(0, 1, 2)
    assert invoice_outcomes(None, gold)["total"] == "missed"


def test_micro_f1_and_bootstrap() -> None:
    counts = [Counts(4, 1, 1), Counts(5, 0, 0)]
    assert micro_f1(counts) == pytest.approx(9 / 10)
    low, high = bootstrap(counts, micro_f1, n=200)
    assert low <= 9 / 10 <= high
    assert bootstrap([0.5] * 10, lambda v: sum(v) / len(v), n=50) == (0.5, 0.5)
    assert all(math.isnan(x) for x in bootstrap([], micro_f1))
