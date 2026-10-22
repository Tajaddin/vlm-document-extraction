"""The whole path on the deployed emulator stack (`docker compose up -d floci` and `make infra-up`): a document posted
to API Gateway reaches the TypeScript Lambda, S3, DynamoDB and SQS; the worker extracts it; the status route returns
the result. Reads the stack's addresses from Terraform's outputs."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest

from vde.config import Settings
from vde.extract.fake import FakeExtractor
from vde.worker.app import Worker

pytestmark = pytest.mark.integration
ENV = Path(__file__).resolve().parents[2] / "infra" / "terraform" / "envs" / "floci"
# a real (tiny) JPEG: the Lambda checks the bytes, not just the declared type
JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9"
)


@pytest.fixture(scope="module")
def stack() -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["terraform", f"-chdir={ENV}", "output", "-json"], capture_output=True, text=True, check=True, timeout=60
        )
        outputs = {k: v["value"] for k, v in json.loads(out.stdout).items()}
    except (OSError, subprocess.SubprocessError, ValueError):
        pytest.skip("the emulator stack is not deployed (make infra-up)")
    if "api_url" not in outputs:
        pytest.skip("the emulator stack is not deployed (make infra-up)")
    return outputs


def test_a_document_goes_in_through_the_api_and_comes_back_extracted(stack: dict[str, Any]) -> None:
    api, key = stack["api_url"], stack["api_key"]
    endpoint = os.environ.get("VDE_AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    unique = JPEG[:-2] + os.urandom(8) + JPEG[-2:]  # a new job each run: ids are content hashes
    with httpx.Client(base_url=api, timeout=120, headers={"x-api-key": key}) as client:
        r = client.post(
            "/v1/documents", params={"kind": "invoice"}, content=unique, headers={"content-type": "image/jpeg"}
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["id"]
        assert client.post(
            "/v1/documents", params={"kind": "invoice"}, content=unique, headers={"content-type": "image/jpeg"}
        ).json()["duplicate"]
        assert client.get(f"/v1/documents/{job_id}").json()["status"] == "queued"

        kwargs = {"endpoint_url": endpoint, "region_name": "us-east-1"}
        settings = Settings(
            queue_url=stack["queue_url"],
            bucket=stack["bucket"],
            table=stack["table"],
            aws_endpoint_url=endpoint,
            worker_wait_s=2,
        )
        worker = Worker(
            settings,
            FakeExtractor(),
            boto3.client("sqs", **kwargs),
            boto3.client("s3", **kwargs),
            boto3.client("dynamodb", **kwargs),
        )
        deadline = time.monotonic() + 60
        body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            worker.poll()
            body = client.get(f"/v1/documents/{job_id}").json()
            if body["status"] == "done":
                break
        assert body["status"] == "done", body
        assert body["result"]["total"] == 100.0 and body["model"] == "fake:fake"
        assert "key" not in body

        assert httpx.get(f"{api}/v1/documents/{job_id}", timeout=30).status_code == 401
