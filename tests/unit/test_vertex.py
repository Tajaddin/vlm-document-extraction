"""The Vertex AI extractor against a response in the documented GenerateContentResponse format (no live call: a live
call bills a Google Cloud project)."""

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types

from vde.config import Settings
from vde.documents import Document
from vde.extract.vertex import VertexExtractor
from vde.schemas import invoice_schema

DOC = Document("i1", "invoice", b"\xff\xd8jpeg")
RESPONSE = {
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"text": '{"total": 575.33, "currency": "EUR"}'}]},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 1290, "candidatesTokenCount": 41, "totalTokenCount": 1331},
    "modelVersion": "gemini-2.5-flash",
}


class Models:
    def __init__(self, result: Any) -> None:
        self.result, self.calls = result, []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_sends_image_schema_and_deterministic_config() -> None:
    models = Models(types.GenerateContentResponse.model_validate(RESPONSE))
    result = VertexExtractor(SimpleNamespace(models=models), "gemini-2.5-flash").extract(DOC)
    assert result.fields == {"total": 575.33, "currency": "EUR"}
    assert (result.prompt_tokens, result.completion_tokens, result.error) == (1290, 41, None)
    call = models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"][0].inline_data.mime_type == "image/jpeg"
    config = call["config"]
    assert config.response_json_schema == invoice_schema()
    assert config.temperature == 0 and config.response_mime_type == "application/json"
    assert config.thinking_config.thinking_budget == 0


def test_api_errors_are_reported_not_raised() -> None:
    error = errors.ClientError(
        429, {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}
    )
    result = VertexExtractor(SimpleNamespace(models=Models(error)), "gemini-2.5-flash").extract(DOC)
    assert result.fields is None and result.error and "429" in result.error


def test_refuses_to_start_without_a_project() -> None:
    with pytest.raises(ValueError, match="bills that project"):
        VertexExtractor.from_settings(Settings(vertex_project=None))
