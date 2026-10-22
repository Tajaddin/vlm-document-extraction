"""The baseline the VLMs have to beat: OCR the page with RapidOCR (PaddleOCR's models on ONNX Runtime, CPU), put the
text back in reading order, and ask a text-only LLM for the same JSON schema."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from vde.documents import Document
from vde.extract import prompts
from vde.extract.base import Extraction, parse_json
from vde.extract.ollama import Ollama, OllamaError
from vde.schemas import ReceiptVariant, schema_for

Box = Sequence[Sequence[float]]  # four (x, y) corners


def reading_order(boxes: Sequence[Box], texts: Sequence[str]) -> list[str]:
    """Group text boxes into printed lines (a box joins a line when its vertical centre falls inside the line's
    span), then lines top to bottom and boxes left to right, joined with two spaces."""
    items: list[dict[str, Any]] = []
    for box, text in zip(boxes, texts, strict=True):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append({"top": min(ys), "bottom": max(ys), "left": min(xs), "text": text})
    items.sort(key=lambda i: (i["top"] + i["bottom"]) / 2)
    lines: list[dict[str, Any]] = []
    for item in items:
        centre = (item["top"] + item["bottom"]) / 2
        line = next((ln for ln in lines if ln["top"] <= centre <= ln["bottom"]), None)
        if line is None:
            lines.append({"top": item["top"], "bottom": item["bottom"], "items": [item]})
        else:
            line["items"].append(item)
            line["top"], line["bottom"] = min(line["top"], item["top"]), max(line["bottom"], item["bottom"])
    lines.sort(key=lambda ln: ln["top"])
    return ["  ".join(i["text"] for i in sorted(ln["items"], key=lambda i: i["left"])) for ln in lines]


class OcrLlmExtractor:
    def __init__(
        self, client: Ollama, model: str, receipt_variant: ReceiptVariant = "required", engine: Any = None
    ) -> None:
        if engine is None:
            from rapidocr import RapidOCR  # optional extra: `uv sync --extra ocr`

            engine = RapidOCR()
        self.engine = engine
        self.client = client
        self.model = model
        self.receipt_variant = receipt_variant
        self.name = "ocr+llm"

    def ocr(self, image: bytes) -> list[str]:
        result = self.engine(image)
        if result.txts is None or result.boxes is None:
            return []
        return reading_order(list(result.boxes), list(result.txts))

    def extract(self, doc: Document) -> Extraction:
        started = time.perf_counter()
        lines = self.ocr(doc.image)
        ocr_seconds = time.perf_counter() - started
        content = prompts.instruction(doc.kind) + "\n\n" + prompts.OCR_PREFIX + "\n".join(lines)
        try:
            body = self.client.chat(
                self.model, [{"role": "user", "content": content}], schema_for(doc.kind, self.receipt_variant)
            )
        except OllamaError as e:
            return Extraction(
                None, self.name, self.model, time.perf_counter() - started, error=str(e), stages={"ocr": ocr_seconds}
            )
        fields, error = parse_json(str((body.get("message") or {}).get("content", "")))
        total = time.perf_counter() - started
        return Extraction(
            fields,
            self.name,
            self.model,
            total,
            error=error,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
            stages={"ocr": ocr_seconds, "llm": total - ocr_seconds},
        )
