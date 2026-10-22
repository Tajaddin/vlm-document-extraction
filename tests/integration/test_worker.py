"""The worker against real S3, SQS and DynamoDB APIs: a Floci container started by Testcontainers. The queue offers a
job again after one second and dead-letters it after two deliveries, so the failure paths run in seconds."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import boto3
import httpx
import pytest
from testcontainers.core.container import DockerContainer

from vde.config import Settings
from vde.documents import Document
from vde.extract.base import Extraction
from vde.extract.fake import FakeExtractor
from vde.worker.app import Worker

pytestmark = pytest.mark.integration
IMAGE = b"\xff\xd8\xff\xe0 not really a jpeg"


class Failing:
    name = "failing"

    def extract(self, doc: Document) -> Extraction:
        return Extraction(None, self.name, "m", 0.1, error="invalid_json")


@pytest.fixture(scope="module")
def aws() -> Iterator[dict[str, Any]]:
    with DockerContainer("floci/floci:2.3.0").with_exposed_ports(4566) as floci:
        url = f"http://{floci.get_container_host_ip()}:{floci.get_exposed_port(4566)}"
        for _ in range(60):
            try:
                if httpx.get(f"{url}/_floci/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        kwargs = {
            "endpoint_url": url,
            "region_name": "us-east-1",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        }
        clients = {name: boto3.client(name, **kwargs) for name in ("s3", "sqs", "dynamodb")}  # type: ignore[call-overload]
        clients["s3"].create_bucket(Bucket="docs")
        clients["dynamodb"].create_table(
            TableName="jobs",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield {"url": url, **clients}


@pytest.fixture
def queues(aws: dict[str, Any], request: pytest.FixtureRequest) -> tuple[str, str]:
    sqs = aws["sqs"]
    name = request.node.name.replace("[", "-").replace("]", "")[:60]
    dlq = sqs.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    queue = sqs.create_queue(
        QueueName=name,
        Attributes={
            "VisibilityTimeout": "1",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "2"}),
        },
    )["QueueUrl"]
    return queue, dlq


def submit(aws: dict[str, Any], queue: str, job_id: str, body: str | None = None) -> None:
    """What the submit Lambda does: image in S3, a queued record in DynamoDB, a message in SQS."""
    aws["s3"].put_object(Bucket="docs", Key=f"incoming/{job_id}.jpg", Body=IMAGE)
    aws["dynamodb"].put_item(
        TableName="jobs", Item={"id": {"S": job_id}, "status": {"S": "queued"}, "kind": {"S": "invoice"}}
    )
    aws["sqs"].send_message(
        QueueUrl=queue,
        MessageBody=body or json.dumps({"id": job_id, "kind": "invoice", "key": f"incoming/{job_id}.jpg"}),
    )


def worker(aws: dict[str, Any], queue: str, extractor: Any) -> Worker:
    settings = Settings(queue_url=queue, bucket="docs", table="jobs", aws_endpoint_url=aws["url"], worker_wait_s=1)
    return Worker(settings, extractor, aws["sqs"], aws["s3"], aws["dynamodb"], max_receive_count=2)


def job(aws: dict[str, Any], job_id: str) -> dict[str, Any]:
    item: dict[str, Any] = aws["dynamodb"].get_item(TableName="jobs", Key={"id": {"S": job_id}})["Item"]
    return item


def depth(aws: dict[str, Any], queue: str) -> int:
    attrs = aws["sqs"].get_queue_attributes(
        QueueUrl=queue, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
    )
    return sum(int(v) for v in attrs["Attributes"].values())


def poll_until(w: Worker, condition: Any, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        w.poll()
        if condition():
            return
    raise AssertionError("condition not reached")


def test_a_job_is_extracted_flagged_stored_and_deleted(aws: dict[str, Any], queues: tuple[str, str]) -> None:
    queue, _ = queues
    submit(aws, queue, "a" * 32)
    assert worker(aws, queue, FakeExtractor()).poll() == 1
    item = job(aws, "a" * 32)
    assert item["status"] == {"S": "done"}
    assert item["result"]["M"]["total"] == {"N": "100.0"}
    assert {f["S"] for f in item["review"]["L"]} == {"no_invoice_number"}  # the stand-in returns no number
    assert item["model"] == {"S": "fake:fake"}
    assert depth(aws, queue) == 0


def test_a_failing_extraction_is_retried_then_failed_and_dead_lettered(
    aws: dict[str, Any], queues: tuple[str, str]
) -> None:
    queue, dlq = queues
    submit(aws, queue, "b" * 32)
    w = worker(aws, queue, Failing())
    poll_until(w, lambda: job(aws, "b" * 32)["status"] == {"S": "failed"})
    assert job(aws, "b" * 32)["error"] == {"S": "invalid_json"}
    poll_until(w, lambda: depth(aws, dlq) == 1)
    assert depth(aws, queue) == 0


def test_a_message_that_is_not_a_job_goes_to_the_dead_letter_queue(
    aws: dict[str, Any], queues: tuple[str, str]
) -> None:
    queue, dlq = queues
    aws["sqs"].send_message(QueueUrl=queue, MessageBody="{not json")
    poll_until(worker(aws, queue, FakeExtractor()), lambda: depth(aws, dlq) == 1)
    assert depth(aws, queue) == 0
