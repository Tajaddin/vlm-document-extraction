"""CORD v2 receipts from the published parquet files. The gold is Donut's `gt_parse` exactly as published; the
evaluator normalises it (a one-item menu is a dict, a longer one a list), so nothing is rewritten here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq

from vde.data.manifest import load_manifest
from vde.documents import Document

Split = Literal["validation", "test"]


def parquet_path(data_dir: Path, split: Split) -> Path:
    for entry in load_manifest()["datasets"]["cord"]["files"]:
        if Path(entry["path"]).name.startswith(split):
            return data_dir / "raw" / "cord" / entry["path"]
    raise ValueError(f"no CORD file for split {split}")


def load(data_dir: Path, split: Split, limit: int | None = None) -> list[Document]:
    path = parquet_path(data_dir, split)
    if not path.is_file():
        raise FileNotFoundError(f"{path}: run `vde fetch` first")
    table = pq.read_table(path)
    rows = table.slice(0, limit).to_pylist() if limit else table.to_pylist()
    docs = []
    for i, row in enumerate(rows):
        gt = json.loads(row["ground_truth"])
        docs.append(
            Document(
                id=f"cord-{split}-{i:03d}",
                kind="receipt",
                image=row["image"]["bytes"],
                gold=gt["gt_parse"],
                meta={"dataset": "cord", "split": split, "index": i},
            )
        )
    return docs
