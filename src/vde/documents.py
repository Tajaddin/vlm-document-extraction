"""A document as every part of the project sees it: an image, which kind of document it is, and (in evaluation) its
gold labels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["receipt", "invoice"]


@dataclass(frozen=True)
class Document:
    id: str
    kind: Kind
    image: bytes
    mime: str = "image/jpeg"
    gold: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # never dump the image bytes into a log or a traceback
        return f"Document(id={self.id!r}, kind={self.kind!r}, bytes={len(self.image)}, meta={self.meta!r})"
