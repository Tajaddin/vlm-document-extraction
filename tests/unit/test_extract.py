import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from vde.documents import Document
from vde.extract.base import parse_json
from vde.extract.fake import FakeExtractor
from vde.extract.ocr import OcrLlmExtractor, reading_order
from vde.extract.ollama import Ollama, VisionExtractor
from vde.schemas import invoice_schema, receipt_schema

URL = "http://ollama.test"
RECEIPT = Document(
    "r1",
    "receipt",
    b"\xff\xd8jpeg",
    gold={"menu": {"nm": "TICKET", "price": "60.000"}, "total": {"total_price": "60.000"}},
)
INVOICE = Document(
    "i1", "invoice", b"\xff\xd8jpeg", gold={"total": "575.33", "invoice_date": "2021-04-21"}, meta={"layout": 2}
)


def answer(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status, json={"message": {"role": "assistant", "content": content}, "prompt_eval_count": 1200, "eval_count": 80}
    )


@respx.mock
def test_vision_extractor_sends_image_schema_and_deterministic_options() -> None:
    route = respx.post(f"{URL}/api/chat").mock(return_value=answer('{"total": {"total_price": "60.000"}, "menu": []}'))
    result = VisionExtractor(Ollama(URL), "qwen3-vl:8b-instruct").extract(RECEIPT)
    assert result.fields == {"total": {"total_price": "60.000"}, "menu": []}
    assert (result.prompt_tokens, result.completion_tokens, result.error) == (1200, 80, None)
    body = json.loads(route.calls[0].request.content)
    assert body["format"] == receipt_schema("required")
    assert body["think"] is False and body["options"]["temperature"] == 0
    assert len(body["messages"]) == 1 and body["messages"][0]["images"]


def test_few_shot_examples_are_earlier_turns_with_their_gold() -> None:
    example = Document("e1", "receipt", b"img", gold={"menu": {"nm": "A", "price": "1"}})
    turns = VisionExtractor(Ollama(URL), "m", [example, example]).messages(RECEIPT)
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant", "user"]
    assert json.loads(turns[1]["content"])["menu"] == [{"nm": "A", "price": "1"}]  # a one-item menu becomes a list


def test_examples_must_be_labelled_documents_of_the_same_kind() -> None:
    with pytest.raises(ValueError, match="not a labelled receipt"):
        VisionExtractor(Ollama(URL), "m", [INVOICE]).messages(RECEIPT)


@respx.mock
def test_invalid_json_is_an_error_not_a_crash() -> None:
    respx.post(f"{URL}/api/chat").mock(return_value=answer("not json"))
    result = VisionExtractor(Ollama(URL), "m").extract(INVOICE)
    assert result.fields is None and result.error == "invalid_json"


@respx.mock
def test_one_server_error_is_retried_two_are_reported() -> None:
    route = respx.post(f"{URL}/api/chat").mock(
        side_effect=[httpx.Response(500, text="loading"), answer('{"total": 1}')]
    )
    assert VisionExtractor(Ollama(URL), "m").extract(INVOICE).fields == {"total": 1}
    assert route.call_count == 2
    respx.post(f"{URL}/api/chat").mock(return_value=httpx.Response(500, text="out of memory"))
    failed = VisionExtractor(Ollama(URL), "m").extract(INVOICE)
    assert failed.fields is None and "500" in (failed.error or "")


def test_reading_order_groups_boxes_into_lines() -> None:
    def box(x: float, y: float, w: float = 40, h: float = 10) -> list[list[float]]:
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    boxes = [box(200, 52), box(10, 50), box(10, 100), box(120, 101, h=8)]
    assert reading_order(boxes, ["16,500", "REAL GANACHE", "TOTAL", "45,500"]) == [
        "REAL GANACHE  16,500",
        "TOTAL  45,500",
    ]


@respx.mock
def test_ocr_baseline_sends_the_text_in_reading_order() -> None:
    route = respx.post(f"{URL}/api/chat").mock(return_value=answer('{"total": 575.33}'))
    engine = lambda _image: SimpleNamespace(  # noqa: E731
        txts=("TOTAL : 575.33 EUR", "COMMERCIAL INVOICE"),
        boxes=([[300, 700], [400, 700], [400, 712], [300, 712]], [[300, 10], [500, 10], [500, 30], [300, 30]]),
    )
    result = OcrLlmExtractor(Ollama(URL), "qwen2.5:7b", engine=engine).extract(INVOICE)
    assert result.fields == {"total": 575.33}
    assert set(result.stages) == {"ocr", "llm"}
    body = json.loads(route.calls[0].request.content)
    assert body["format"] == invoice_schema()
    content = body["messages"][0]["content"]
    assert content.index("COMMERCIAL INVOICE") < content.index("TOTAL : 575.33 EUR")
    assert "images" not in body["messages"][0]


def test_fake_extractor_and_parse_json() -> None:
    assert FakeExtractor().extract(INVOICE).fields["total"] == 100.0
    assert FakeExtractor(echo_gold=True).extract(INVOICE).fields["total"] == 575.33
    assert parse_json("[1, 2]") == (None, "not_an_object")


@respx.mock
def test_an_answer_cut_off_at_the_output_cap_is_a_failure() -> None:
    route = respx.post(f"{URL}/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": '{"total": 1}' + " " * 50}, "done_reason": "length", "eval_count": 2048}
        )
    )
    result = VisionExtractor(Ollama(URL, num_predict=2048), "m").extract(INVOICE)
    assert result.fields is None and result.error == "truncated"
    assert json.loads(route.calls[0].request.content)["options"]["num_predict"] == 2048
