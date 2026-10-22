"""Tree edit distance (Zhang and Shasha, 1989) with caller-supplied costs: the algorithm behind Donut's normalised
tree-edit-distance accuracy. Written here instead of depending on `zss`, whose licence is not stated."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Node:
    label: str
    children: list[Node] = field(default_factory=list)

    def add(self, child: Node) -> Node:
        self.children.append(child)
        return self


Cost = Callable[[Node], float]
UpdateCost = Callable[[Node, Node], float]


def _postorder(root: Node) -> tuple[list[Node], list[int]]:
    """Nodes in post-order and, for each, the post-order index of its leftmost leaf descendant."""
    nodes: list[Node] = []
    lmd: list[int] = []

    def visit(node: Node) -> int:
        first: int | None = None
        for child in node.children:
            leftmost = visit(child)
            if first is None:
                first = leftmost
        nodes.append(node)
        own = len(nodes) - 1
        lmd.append(first if first is not None else own)
        return lmd[-1]

    visit(root)
    return nodes, lmd


def _keyroots(lmd: list[int]) -> list[int]:
    """The highest-numbered node for each distinct leftmost leaf: the subtrees whose forests are computed."""
    last: dict[int, int] = {}
    for i, leftmost in enumerate(lmd):
        last[leftmost] = i
    return sorted(last.values())


def distance(a: Node, b: Node, insert: Cost, remove: Cost, update: UpdateCost) -> float:
    nodes_a, lmd_a = _postorder(a)
    nodes_b, lmd_b = _postorder(b)
    td = [[0.0] * len(nodes_b) for _ in nodes_a]

    def forest(i: int, j: int) -> None:
        li, lj = lmd_a[i], lmd_b[j]
        rows, cols = i - li + 2, j - lj + 2
        ioff, joff = li - 1, lj - 1
        fd = [[0.0] * cols for _ in range(rows)]
        for x in range(1, rows):
            fd[x][0] = fd[x - 1][0] + remove(nodes_a[x + ioff])
        for y in range(1, cols):
            fd[0][y] = fd[0][y - 1] + insert(nodes_b[y + joff])
        for x in range(1, rows):
            for y in range(1, cols):
                na, nb = nodes_a[x + ioff], nodes_b[y + joff]
                delete_cost = fd[x - 1][y] + remove(na)
                insert_cost = fd[x][y - 1] + insert(nb)
                if lmd_a[x + ioff] == li and lmd_b[y + joff] == lj:
                    fd[x][y] = min(delete_cost, insert_cost, fd[x - 1][y - 1] + update(na, nb))
                    td[x + ioff][y + joff] = fd[x][y]
                else:
                    p, q = lmd_a[x + ioff] - 1 - ioff, lmd_b[y + joff] - 1 - joff
                    fd[x][y] = min(delete_cost, insert_cost, fd[p][q] + td[x + ioff][y + joff])

    for i in _keyroots(lmd_a):
        for j in _keyroots(lmd_b):
            forest(i, j)
    return td[-1][-1]


def levenshtein(s: str, t: str) -> int:
    previous = list(range(len(t) + 1))
    for i, cs in enumerate(s, 1):
        current = [i]
        for j, ct in enumerate(t, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (cs != ct)))
        previous = current
    return previous[-1]
