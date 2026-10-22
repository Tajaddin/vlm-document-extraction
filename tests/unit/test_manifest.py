import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from vde.data import manifest

CONTENT = b"receipt bytes"


def entry(**checksum: str) -> dict[str, object]:
    return {"path": "f.bin", "url": "https://data.test/f.bin", "size": len(CONTENT), **checksum}


def make(**checksum: str) -> dict[str, object]:
    return {"datasets": {"demo": {"files": [entry(**checksum)]}, "other": {"files": []}}}


@respx.mock
def test_fetch_downloads_and_checks_the_published_checksum(tmp_path: Path) -> None:
    respx.get("https://data.test/f.bin").mock(return_value=httpx.Response(200, content=CONTENT))
    rows = manifest.fetch(tmp_path, make(sha256=hashlib.sha256(CONTENT).hexdigest()), only="demo")
    assert rows == [{"dataset": "demo", "path": "f.bin", "present": True, "size_ok": True, "sha256_ok": True}]
    assert (tmp_path / "raw" / "demo" / "f.bin").read_bytes() == CONTENT


@respx.mock
def test_a_file_that_does_not_match_is_not_kept(tmp_path: Path) -> None:
    respx.get("https://data.test/f.bin").mock(return_value=httpx.Response(200, content=b"tampered!!!!!"))
    with pytest.raises(RuntimeError, match="md5"):
        manifest.fetch(tmp_path, make(md5="0" * 32))
    assert not list((tmp_path / "raw" / "demo").iterdir())


def test_verify_reports_missing_files_and_an_entry_needs_a_checksum(tmp_path: Path) -> None:
    assert manifest.verify(tmp_path, make(md5="x")) == [{"dataset": "demo", "path": "f.bin", "present": False}]
    with pytest.raises(ValueError, match="no checksum"):
        manifest.expected({"path": "f.bin"})


def test_the_committed_manifest_pins_every_file() -> None:
    for dataset in manifest.load_manifest()["datasets"].values():
        assert dataset["license"] == "CC BY 4.0"
        for e in dataset["files"]:
            assert e["size"] > 0 and manifest.expected(e)
