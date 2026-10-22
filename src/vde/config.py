"""Settings from environment variables (prefix VDE_). Nothing here is a secret: the local stack needs none, and the
API key the Lambdas check lives in Terraform state on the emulator and in Secrets Manager on AWS."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VDE_", env_file=".env", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Path("data")

    # local models (Ollama on the host, GPU)
    ollama_url: str = "http://127.0.0.1:11434"
    vlm_model: str = "qwen3-vl:8b-instruct"
    text_model: str = "qwen2.5:7b"
    num_ctx: int = 8192
    request_timeout_s: float = 300.0

    # which extractor the worker runs: a VLM through Ollama, the OCR baseline, Gemini on Vertex, or the CI stand-in
    extractor: Literal["vlm", "ocr", "vertex", "fake"] = "vlm"
    few_shot: int = 0

    # the serverless side (Floci locally; real AWS when the endpoint is unset)
    aws_endpoint_url: str | None = "http://127.0.0.1:4566"
    aws_region: str = "us-east-1"
    queue_url: str | None = None
    bucket: str = "vde-documents"
    table: str = "vde-jobs"
    worker_metrics_port: int = 9108
    worker_wait_s: int = 10

    # Vertex AI (only with the owner's billing go-ahead)
    vertex_project: str | None = None
    vertex_location: str = "us-central1"
    vertex_model: str = "gemini-2.5-flash"


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
