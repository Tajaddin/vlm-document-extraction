"""Download the datasets and check every file against the checksum its publisher states (Hugging Face's LFS sha256
for CORD at a pinned revision, Zenodo's md5 for FATURA). The manifest is committed: evals/data-manifest.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from vde import log

MANIFEST = Path(__file__).resolve().parents[3] / "evals" / "data-manifest.json"
logger = log.get(__name__)


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected(entry: dict[str, Any]) -> tuple[str, str]:
    for algorithm in ("sha256", "md5"):
        if algorithm in entry:
            return algorithm, str(entry[algorithm])
    raise ValueError(f"no checksum for {entry['path']}")


def _selected(manifest: dict[str, Any], only: str | None) -> list[tuple[str, dict[str, Any]]]:
    return [(name, ds) for name, ds in manifest["datasets"].items() if only in (None, name)]


def verify(data_dir: Path, manifest: dict[str, Any] | None = None, only: str | None = None) -> list[dict[str, Any]]:
    """One row per file: present, size and checksum as published."""
    manifest = manifest or load_manifest()
    rows = []
    for name, dataset in _selected(manifest, only):
        for entry in dataset["files"]:
            path = data_dir / "raw" / name / entry["path"]
            algorithm, want = expected(entry)
            row = {"dataset": name, "path": entry["path"], "present": path.is_file()}
            if path.is_file():
                row["size_ok"] = path.stat().st_size == entry["size"]
                row[f"{algorithm}_ok"] = digest(path, algorithm) == want
            rows.append(row)
    return rows


def fetch(data_dir: Path, manifest: dict[str, Any] | None = None, only: str | None = None) -> list[dict[str, Any]]:
    """Download what is missing or wrong; refuse to keep a file whose checksum differs from the publisher's."""
    manifest = manifest or load_manifest()
    for name, dataset in _selected(manifest, only):
        for entry in dataset["files"]:
            path = data_dir / "raw" / name / entry["path"]
            algorithm, want = expected(entry)
            if path.is_file() and path.stat().st_size == entry["size"] and digest(path, algorithm) == want:
                logger.info("dataset_file_ok", dataset=name, path=entry["path"])
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(path.suffix + ".part")
            logger.info("dataset_file_download", dataset=name, path=entry["path"], bytes=entry["size"])
            with (
                httpx.stream("GET", entry["url"], follow_redirects=True, timeout=120) as r,
                partial.open("wb") as out,
            ):
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
            got = digest(partial, algorithm)
            if got != want:
                partial.unlink()
                raise RuntimeError(f"{entry['path']}: {algorithm} {got} != published {want}")
            partial.replace(path)
    return verify(data_dir, manifest, only)
