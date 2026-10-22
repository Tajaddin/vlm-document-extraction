"""Vision-language models through Ollama's chat API, answering in the document kind's JSON schema.

Few-shot examples are earlier turns of the same chat: the example's image with the instruction, then its gold JSON as
the assistant's answer. The caller picks the examples, and the evaluation only ever passes documents from the
validation split (CORD) or from training layouts (FATURA)."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Sequence
from typing import Any

import httpx

from vde import log
from vde.documents import Document
from vde.extract import prompts
from vde.extract.base import Extraction, parse_json
from vde.schemas import ReceiptVariant, as_example, schema_for

logger = log.get(__name__)


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, url: str, timeout_s: float = 300.0, num_ctx: int = 8192, num_predict: int = 2048) -> None:
        self.http = httpx.Client(base_url=url, timeout=timeout_s)
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def chat(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "think": False,  # thinking variants spend their budget on hidden reasoning; the answer is the JSON
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": self.num_predict, "seed": 0},
            "keep_alive": "10m",
        }
        for attempt in (1, 2):  # a model being loaded or swapped can answer 500 once
            try:
                r = self.http.post("/api/chat", json=body)
            except httpx.TransportError as e:
                if attempt == 2:
                    raise OllamaError(f"ollama unreachable: {e}") from e
                continue
            if r.status_code < 500 or attempt == 2:
                break
            logger.warning("ollama_retry", status=r.status_code, model=model)
        if r.status_code != 200:
            raise OllamaError(f"ollama {r.status_code}: {r.text[:200]}")
        result: dict[str, Any] = r.json()
        return result


def answer(body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The parsed answer, or why there is none. An answer cut off at the output cap counts as a failure even when the
    JSON happens to close: the model was emitting filler (constrained decoding allows unlimited whitespace)."""
    if body.get("done_reason") == "length":
        return None, "truncated"
    return parse_json(str((body.get("message") or {}).get("content", "")))


def _b64(image: bytes) -> str:
    return base64.b64encode(image).decode("ascii")


class VisionExtractor:
    """One VLM, zero-shot (no examples) or few-shot."""

    def __init__(
        self,
        client: Ollama,
        model: str,
        examples: Sequence[Document] = (),
        receipt_variant: ReceiptVariant = "required",
    ) -> None:
        self.client = client
        self.model = model
        self.examples = list(examples)
        self.receipt_variant = receipt_variant
        self.name = f"vlm-{len(self.examples)}shot"

    def messages(self, doc: Document) -> list[dict[str, Any]]:
        instruction = prompts.instruction(doc.kind)
        turns: list[dict[str, Any]] = []
        for ex in self.examples:
            if ex.kind != doc.kind or ex.gold is None:
                raise ValueError(f"example {ex.id} is not a labelled {doc.kind}")
            turns.append({"role": "user", "content": instruction, "images": [_b64(ex.image)]})
            turns.append({"role": "assistant", "content": json.dumps(as_example(ex.kind, ex.gold), ensure_ascii=False)})
        turns.append({"role": "user", "content": instruction, "images": [_b64(doc.image)]})
        return turns

    def extract(self, doc: Document) -> Extraction:
        started = time.perf_counter()
        try:
            body = self.client.chat(self.model, self.messages(doc), schema_for(doc.kind, self.receipt_variant))
        except OllamaError as e:
            return Extraction(None, self.name, self.model, time.perf_counter() - started, error=str(e))
        fields, error = answer(body)
        return Extraction(
            fields,
            self.name,
            self.model,
            time.perf_counter() - started,
            error=error,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )
