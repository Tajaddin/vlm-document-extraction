"""Consume extraction jobs from SQS: read the image from S3, extract, attach review flags, write the result to
DynamoDB, delete the message.

Inference needs the GPU, so this runs next to it rather than in Lambda (ADR 0003). Failure handling leans on SQS:
a job that fails is not deleted, so SQS offers it again after the visibility timeout and, after `max_receive_count`
deliveries, moves it to the dead-letter queue; the worker marks the job `failed` on its last delivery so the client
sees why. A message that is not a job at all is left for the dead-letter queue the same way."""

from __future__ import annotations

import json
import signal
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from vde import checks, log
from vde.config import Settings
from vde.documents import Document
from vde.extract.base import Extractor

logger = log.get(__name__)

JOBS = Counter("vde_worker_jobs_total", "Jobs handled, by document kind and outcome", ["kind", "outcome"])
SECONDS = Histogram(
    "vde_worker_extraction_seconds", "Extraction time per job", ["kind"], buckets=(1, 2, 4, 8, 16, 32, 64, 128)
)
FLAGS = Counter("vde_worker_review_flags_total", "Review flags raised, by kind and flag", ["kind", "flag"])
FLAGGED = Counter("vde_worker_flagged_jobs_total", "Jobs with at least one review flag", ["kind"])
LAST_POLL = Gauge("vde_worker_last_poll_timestamp_seconds", "When the worker last asked SQS for work")
QUEUED = Gauge("vde_worker_queue_messages", "Messages in the job queue, by state", ["state"])
HEARTBEAT = Path(tempfile.gettempdir()) / "vde-worker-heartbeat"  # /tmp in the container; the health check reads it


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Worker:
    def __init__(
        self, settings: Settings, extractor: Extractor, sqs: Any, s3: Any, dynamo: Any, max_receive_count: int = 3
    ) -> None:
        if not settings.queue_url:
            raise ValueError("VDE_QUEUE_URL is not set (terraform output queue_url)")
        self.s = settings
        self.queue_url = settings.queue_url
        self.extractor = extractor
        self.sqs, self.s3, self.dynamo = sqs, s3, dynamo
        self.max_receive_count = max_receive_count
        self.stopping = False

    def poll(self) -> int:
        """One long-poll; handles what arrives and returns how many messages it saw."""
        LAST_POLL.set_to_current_time()
        HEARTBEAT.touch(exist_ok=True)
        response = self.sqs.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=self.s.worker_wait_s,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        for message in messages:
            self.handle(message)
        return len(messages)

    def handle(self, message: dict[str, Any]) -> None:
        receives = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            job = json.loads(message["Body"])
            job_id, kind, key = job["id"], job["kind"], job["key"]
            if kind not in ("receipt", "invoice"):
                raise ValueError(kind)
        except (ValueError, KeyError, TypeError):
            JOBS.labels("unknown", "poison").inc()
            logger.error("poison_message", message_id=message.get("MessageId"), receives=receives)
            return  # not deleted: SQS moves it to the dead-letter queue after max_receive_count deliveries

        self._update(job_id, {"status": "processing", "updatedAt": _now()})
        image = self.s3.get_object(Bucket=self.s.bucket, Key=key)["Body"].read()
        doc = Document(id=job_id, kind=kind, image=image)
        result = self.extractor.extract(doc)
        SECONDS.labels(kind).observe(result.seconds)

        if result.fields is None:
            last = receives >= self.max_receive_count
            JOBS.labels(kind, "failed" if last else "retry").inc()
            logger.warning("extraction_failed", job=job_id, error=result.error, receives=receives, last=last)
            if last:
                self._update(job_id, {"status": "failed", "error": result.error or "unknown", "updatedAt": _now()})
            return  # not deleted: offered again, then dead-lettered

        review = checks.flags(kind, result.fields)
        for flag in review:
            FLAGS.labels(kind, flag).inc()
        if review:
            FLAGGED.labels(kind).inc()
        self._update(
            job_id,
            {
                "status": "done",
                "result": result.fields,
                "review": review,
                "model": f"{result.approach}:{result.model}",
                "seconds": round(result.seconds, 3),
                "updatedAt": _now(),
            },
        )
        self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message["ReceiptHandle"])
        JOBS.labels(kind, "done").inc()
        logger.info("job_done", job=job_id, kind=kind, seconds=round(result.seconds, 2), review=review)

    def _update(self, job_id: str, values: dict[str, Any]) -> None:
        names = {f"#{k}": k for k in values}
        self.dynamo.update_item(
            TableName=self.s.table,
            Key={"id": {"S": job_id}},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in values),
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues={f":{k}": _attr(v) for k, v in values.items()},
        )

    def queue_depth(self) -> None:
        attrs = self.sqs.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        QUEUED.labels("waiting").set(int(attrs.get("ApproximateNumberOfMessages", 0)))
        QUEUED.labels("in_flight").set(int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)))

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        start_http_server(self.s.worker_metrics_port)
        logger.info("worker_started", queue=self.queue_url, extractor=getattr(self.extractor, "name", "?"))
        last_depth = 0.0
        while not self.stopping:
            try:
                self.poll()
                if time.monotonic() - last_depth > 30:
                    self.queue_depth()
                    last_depth = time.monotonic()
            except Exception:  # keep consuming: one bad job or a blip in AWS must not stop the worker
                logger.exception("poll_failed")
                time.sleep(5)
        logger.info("worker_stopped")


def _attr(value: Any) -> dict[str, Any]:
    """A Python value as a DynamoDB attribute (the low-level client, so the worker needs no resource layer)."""
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, int | float):
        return {"N": str(value)}
    if isinstance(value, list):
        return {"L": [_attr(v) for v in value]}
    if isinstance(value, dict):
        return {"M": {str(k): _attr(v) for k, v in value.items()}}
    raise TypeError(f"cannot store {type(value).__name__}")


def build(settings: Settings) -> Worker:
    import boto3

    from vde.extract.fake import FakeExtractor
    from vde.extract.ollama import Ollama, VisionExtractor

    extractor: Extractor
    if settings.extractor == "fake":
        extractor = FakeExtractor()
    elif settings.extractor == "ocr":
        from vde.extract.ocr import OcrLlmExtractor

        extractor = OcrLlmExtractor(
            Ollama(settings.ollama_url, settings.request_timeout_s, settings.num_ctx, settings.max_output_tokens),
            settings.text_model,
        )
    elif settings.extractor == "vertex":
        from vde.extract.vertex import VertexExtractor

        extractor = VertexExtractor.from_settings(settings)
    else:
        extractor = VisionExtractor(
            Ollama(settings.ollama_url, settings.request_timeout_s, settings.num_ctx, settings.max_output_tokens),
            settings.vlm_model,
        )
    kwargs = {"region_name": settings.aws_region, "endpoint_url": settings.aws_endpoint_url or None}
    return Worker(
        settings,
        extractor,
        boto3.client("sqs", **kwargs),
        boto3.client("s3", **kwargs),
        boto3.client("dynamodb", **kwargs),
    )
