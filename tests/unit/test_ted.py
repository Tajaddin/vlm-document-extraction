from vde.ted import Node, distance, levenshtein


def unit(_: Node) -> float:
    return 1.0


def relabel(a: Node, b: Node) -> float:
    return float(a.label != b.label)


def n(label: str, *children: Node) -> Node:
    return Node(label, list(children))


def test_identical_trees_are_zero_apart() -> None:
    a = n("f", n("a", n("h"), n("c", n("l"))), n("e"))
    assert distance(a, a, unit, unit, relabel) == 0


def test_two_relabels() -> None:  # the example in zss's README
    a = n("f", n("a", n("h"), n("c", n("l"))), n("e"))
    b = n("f", n("a", n("d"), n("c", n("b"))), n("e"))
    assert distance(a, b, unit, unit, relabel) == 2


def test_zhang_shasha_paper_example() -> None:
    # f(d(a c(b)) e) -> f(c(d(a b)) e): delete c under d, insert c above d
    a = n("f", n("d", n("a"), n("c", n("b"))), n("e"))
    b = n("f", n("c", n("d", n("a"), n("b"))), n("e"))
    assert distance(a, b, unit, unit, relabel) == 2


def test_insertions_cost_what_the_cost_function_says() -> None:
    a = n("r")
    b = n("r", n("x"), n("y", n("z")))
    assert distance(a, b, unit, unit, relabel) == 3
    assert distance(b, a, unit, unit, relabel) == 3


def test_levenshtein() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("45,500", "45,500") == 0
