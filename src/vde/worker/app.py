"""Consume extraction jobs from SQS: read the image from S3, extract, attach review flags, write the result to
DynamoDB, delete the message.

Inference needs the GPU, so this runs next to it rather than in Lambda (ADR 0003). Failure handling leans on SQS:
a job that fails (no answer from the extractor, or anything raised on the way) is not deleted, so SQS offers it again
after the visibility timeout and, after `max_receive_count` deliveries, moves it to the dead-letter queue; the worker
marks the job `failed` on its last delivery so the client sees why. A message that is not a job at all is left for the
dead-letter queue the same way. A message for a job that is already done is deleted without extracting it again."""

from __future__ import annotations

import json
import signal
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from PIL import Image
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from vde import checks, log
from vde.config import Settings
from vde.documents import Document, Kind
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
            VisibilityTimeout=self.s.worker_visibility_s,
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

        try:
            self._update(job_id, {"status": "processing", "updatedAt": _now()}, unless="done")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            # a second message for a job already done (a resend or a redrive queued it again), or a record that is gone
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message["ReceiptHandle"])
            JOBS.labels(kind, "skipped").inc()
            logger.info("job_skipped", job=job_id, receives=receives)
            return

        try:
            with self._hidden(message["ReceiptHandle"]):
                error = self._run(job_id, kind, key)
        except Exception as e:  # whatever goes wrong, the job must not stay "processing" after its last delivery
            logger.exception("job_crashed", job=job_id, receives=receives)
            error = f"worker: {type(e).__name__}"

        if error is not None:
            last = receives >= self.max_receive_count
            JOBS.labels(kind, "failed" if last else "retry").inc()
            logger.warning("extraction_failed", job=job_id, error=error, receives=receives, last=last)
            if last:
                self._update(job_id, {"status": "failed", "error": error, "updatedAt": _now()})
            return  # not deleted: offered again, then dead-lettered

        self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message["ReceiptHandle"])
        JOBS.labels(kind, "done").inc()

    def _run(self, job_id: str, kind: Kind, key: str) -> str | None:
        """Extract the document and store the result as `done`; the reason, when there is no result."""
        image = self.s3.get_object(Bucket=self.s.bucket, Key=key)["Body"].read()
        # the size from the header alone, read by PIL, which the OCR path decodes with (submit has its own reader)
        with Image.open(BytesIO(image)) as header:
            width, height = header.size
        if width * height > self.s.max_pixels:
            return f"image too large: {width} x {height} pixels"
        result = self.extractor.extract(Document(id=job_id, kind=kind, image=image))
        SECONDS.labels(kind).observe(result.seconds)
        if result.fields is None:
            return result.error or "unknown"

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
        logger.info("job_done", job=job_id, kind=kind, seconds=round(result.seconds, 2), review=review)
        return None

    @contextmanager
    def _hidden(self, receipt_handle: str) -> Iterator[None]:
        """Extend the message's visibility every third of the timeout while the job runs, so SQS never offers a slow
        extraction to another worker halfway through (it would run twice)."""
        done = threading.Event()

        def extend() -> None:
            while not done.wait(self.s.worker_visibility_s / 3):
                try:
                    self.sqs.change_message_visibility(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=receipt_handle,
                        VisibilityTimeout=self.s.worker_visibility_s,
                    )
                except Exception:  # the next attempt may get through; at worst SQS offers the job again
                    logger.warning("visibility_not_extended", exc_info=True)

        thread = threading.Thread(target=extend, name="visibility", daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()

    def _update(self, job_id: str, values: dict[str, Any], unless: str | None = None) -> None:
        """Set `values` on the job's record; with `unless`, only while the job is not in that state."""
        names = {f"#{k}": k for k in values}
        attrs = {f":{k}": _attr(v) for k, v in values.items()}
        condition = "attribute_exists(id)"
        if unless is not None:
            names["#status"] = "status"
            attrs[":unless"] = _attr(unless)
            condition += " AND #status <> :unless"
        self.dynamo.update_item(
            TableName=self.s.table,
            Key={"id": {"S": job_id}},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in values),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=attrs,
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
