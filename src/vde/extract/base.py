"""What every extractor returns, and the interface the evaluation and the worker call."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from vde.documents import Document


@dataclass
class Extraction:
    fields: dict[str, Any] | None
    approach: str
    model: str
    seconds: float
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    stages: dict[str, float] = field(default_factory=dict)  # e.g. OCR seconds vs LLM seconds

    def as_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "approach": self.approach,
            "model": self.model,
            "seconds": round(self.seconds, 3),
            "error": self.error,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "stages": {k: round(v, 3) for k, v in self.stages.items()},
        }


class Extractor(Protocol):
    name: str

    def extract(self, doc: Document) -> Extraction: ...


def parse_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """The model's answer as a dict, or the reason it is not one."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(value, dict):
        return None, "not_an_object"
    return value, None
