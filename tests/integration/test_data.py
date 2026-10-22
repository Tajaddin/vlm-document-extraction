"""The document sets themselves, on the downloaded data (`vde fetch`): sizes, and that nothing scored is ever shown
to a model as an example."""

from __future__ import annotations

from pathlib import Path

import pytest

from vde.cli import documents, examples
from vde.data.manifest import load_manifest

pytestmark = pytest.mark.data
DATA = Path("data")


@pytest.fixture(scope="module", autouse=True)
def need_data() -> None:
    files = [DATA / "raw" / name / f["path"] for name, ds in load_manifest()["datasets"].items() for f in ds["files"]]
    if not all(p.is_file() for p in files):
        pytest.skip("datasets not downloaded (vde fetch)")


def test_cord_sets() -> None:
    test = documents("cord", "test")
    assert len(test) == 100 and all(d.gold for d in test)
    shown = examples("cord", 2, {d.id for d in test})
    assert {d.meta["split"] for d in shown} == {"validation"}


def test_fatura_test_is_ten_held_out_layouts_and_examples_come_from_the_others() -> None:
    test = documents("fatura", "test")
    layouts = {d.meta["layout"] for d in test}
    assert len(test) == 100 and layouts == {2, 4, 7, 10, 12, 25, 32, 39, 49, 50}
    shown = examples("fatura", 3, {d.id for d in test})
    assert len({d.meta["layout"] for d in shown}) == 3
    assert not {d.meta["layout"] for d in shown} & layouts
    assert documents("fatura", "test")[0].id == test[0].id  # the sample is fixed


def test_dev_sets_never_overlap_test() -> None:
    for dataset in ("cord", "fatura"):
        dev = {d.id for d in documents(dataset, "dev")}  # type: ignore[arg-type]
        test = {d.id for d in documents(dataset, "test")}  # type: ignore[arg-type]
        assert dev and not dev & test
