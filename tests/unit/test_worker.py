"""The worker's job states with stand-in AWS clients: every job ends `done` or `failed`, whatever the extractor does,
and a job is never offered to a second worker while the first is still on it. The same paths against real SQS and
DynamoDB APIs are in tests/integration/test_worker.py."""

from __future__ import annotations

import json
import struct
import threading
import zlib
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from vde.config import Settings
from vde.documents import Document
from vde.extract.base import Extraction
from vde.extract.fake import FakeExtractor
from vde.worker.app import Worker

JOB = "a" * 32


def message(receives: int) -> dict[str, Any]:
    return {
        "Body": json.dumps({"id": JOB, "kind": "invoice", "key": f"incoming/{JOB}.png"}),
        "ReceiptHandle": "handle",
        "MessageId": "m1",
        "Attributes": {"ApproximateReceiveCount": str(receives)},
    }


class Crashing:
    name = "crashing"

    def extract(self, doc: Document) -> Extraction:
        raise MemoryError("decoding the image")


def png(width: int, height: int) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


def clients(image: bytes = png(4, 3)) -> tuple[MagicMock, MagicMock, MagicMock]:
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": MagicMock(read=lambda: image)}
    return MagicMock(), s3, MagicMock()


def statuses(dynamo: MagicMock) -> list[str]:
    return [c.kwargs["ExpressionAttributeValues"][":status"]["S"] for c in dynamo.update_item.call_args_list]


def test_an_extractor_crash_on_the_last_delivery_fails_the_job() -> None:
    sqs, s3, dynamo = clients()
    Worker(Settings(queue_url="q"), Crashing(), sqs, s3, dynamo).handle(message(receives=3))
    assert statuses(dynamo) == ["processing", "failed"]
    assert dynamo.update_item.call_args.kwargs["ExpressionAttributeValues"][":error"] == {"S": "worker: MemoryError"}
    sqs.delete_message.assert_not_called()  # SQS dead-letters it


def test_an_extractor_crash_before_the_last_delivery_leaves_the_job_for_a_retry() -> None:
    sqs, s3, dynamo = clients()
    Worker(Settings(queue_url="q"), Crashing(), sqs, s3, dynamo).handle(message(receives=1))
    assert statuses(dynamo) == ["processing"]
    sqs.delete_message.assert_not_called()


def test_a_result_the_table_refuses_fails_the_job_on_the_last_delivery() -> None:
    sqs, s3, dynamo = clients()

    def update(**kwargs: Any) -> None:
        if kwargs["ExpressionAttributeValues"][":status"] == {"S": "done"}:
            raise ClientError({"Error": {"Code": "ValidationException", "Message": "bad number"}}, "UpdateItem")

    dynamo.update_item.side_effect = update
    Worker(Settings(queue_url="q"), FakeExtractor(), sqs, s3, dynamo).handle(message(receives=3))
    assert statuses(dynamo) == ["processing", "done", "failed"]
    sqs.delete_message.assert_not_called()


def test_a_job_that_cannot_be_marked_failed_is_not_swallowed() -> None:
    sqs, s3, dynamo = clients()
    dynamo.update_item.side_effect = [None, ClientError({"Error": {"Code": "Throttled", "Message": ""}}, "UpdateItem")]
    with pytest.raises(ClientError):
        Worker(Settings(queue_url="q"), Crashing(), sqs, s3, dynamo).handle(message(receives=3))


def test_an_image_larger_than_its_first_header_says_is_not_extracted() -> None:
    image = png(40, 30)
    small = struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    decoy = small + struct.pack(">I", zlib.crc32(small[4:]))
    sqs, s3, dynamo = clients(image[:8] + decoy + image[8:])  # PIL decodes it at the size of the last IHDR
    Worker(Settings(queue_url="q", max_pixels=1000), FakeExtractor(), sqs, s3, dynamo).handle(message(receives=3))
    assert statuses(dynamo) == ["processing", "failed"]
    error = dynamo.update_item.call_args.kwargs["ExpressionAttributeValues"][":error"]
    assert error == {"S": "image too large: 40 x 30 pixels"}


def test_the_message_stays_hidden_while_a_slow_extraction_runs() -> None:
    sqs, s3, dynamo = clients()
    extended = threading.Event()
    sqs.change_message_visibility.side_effect = lambda **_: extended.set()

    class Slow:
        name = "slow"

        def extract(self, doc: Document) -> Extraction:
            assert extended.wait(5), "visibility was not extended while the job ran"
            return FakeExtractor().extract(doc)

    worker = Worker(Settings(queue_url="q", worker_visibility_s=1), Slow(), sqs, s3, dynamo)
    worker.handle(message(receives=1))
    sqs.change_message_visibility.assert_called_with(QueueUrl="q", ReceiptHandle="handle", VisibilityTimeout=1)
    assert statuses(dynamo) == ["processing", "done"]
    calls = sqs.change_message_visibility.call_count
    threading.Event().wait(0.5)
    assert sqs.change_message_visibility.call_count == calls  # stops once the job is over


def test_messages_are_received_with_the_visibility_the_worker_extends() -> None:
    sqs, s3, dynamo = clients()
    sqs.receive_message.return_value = {}
    Worker(Settings(queue_url="q", worker_visibility_s=600), FakeExtractor(), sqs, s3, dynamo).poll()
    assert sqs.receive_message.call_args.kwargs["VisibilityTimeout"] == 600
