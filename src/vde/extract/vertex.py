"""Gemini on Vertex AI through the Google Gen AI SDK, behind the same interface and JSON schema as the local models.

A call bills the configured Google Cloud project (Gemini 3.8 Flash: $0.75 per million input tokens and $3.75 per
million output in October 2026), so nothing in this repository calls it on its own: the tests use a response in the
documented `GenerateContentResponse` format, and a live run needs VDE_VERTEX_PROJECT and the owner's credentials
(docs/DEPLOY.md)."""

from __future__ import annotations

import time
from typing import Any

from vde.config import Settings
from vde.documents import Document
from vde.extract import prompts
from vde.extract.base import Extraction, parse_json
from vde.schemas import ReceiptVariant, schema_for


class VertexExtractor:
    def __init__(self, client: Any, model: str, receipt_variant: ReceiptVariant = "required") -> None:
        self.client = client
        self.model = model
        self.receipt_variant = receipt_variant
        self.name = "vertex-0shot"

    @classmethod
    def from_settings(cls, settings: Settings) -> VertexExtractor:
        from google import genai  # optional extra: `uv sync --extra vertex`

        if not settings.vertex_project:
            raise ValueError("VDE_VERTEX_PROJECT is not set; a Vertex AI run bills that project (docs/DEPLOY.md)")
        client = genai.Client(vertexai=True, project=settings.vertex_project, location=settings.vertex_location)
        return cls(client, settings.vertex_model)

    def config(self, kind: str) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            temperature=0,
            seed=0,
            response_mime_type="application/json",
            response_json_schema=schema_for(kind, self.receipt_variant),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

    def extract(self, doc: Document) -> Extraction:
        from google.genai import errors, types

        started = time.perf_counter()
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=doc.image, mime_type=doc.mime), prompts.instruction(doc.kind)],
                config=self.config(doc.kind),
            )
        except errors.APIError as e:
            return Extraction(
                None, self.name, self.model, time.perf_counter() - started, error=f"vertex {e.code}: {e.message}"
            )
        fields, error = parse_json(response.text or "")
        usage = response.usage_metadata
        return Extraction(
            fields,
            self.name,
            self.model,
            time.perf_counter() - started,
            error=error,
            prompt_tokens=usage.prompt_token_count if usage else None,
            completion_tokens=usage.candidates_token_count if usage else None,
        )
