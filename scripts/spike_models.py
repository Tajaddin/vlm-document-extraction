"""Spike (#2): one CORD validation receipt through each candidate VLM, twice, with the receipt JSON schema. Records
cold and warm latency, where Ollama placed the model (GPU or partly CPU) and what it answered.

    uv run python scripts/spike_models.py --out reports/dev/spike.json

It decides which models get a full evaluation; one receipt says nothing about accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from vde.config import settings
from vde.data import cord
from vde.extract.ollama import Ollama, VisionExtractor

CANDIDATES = ("qwen2.5vl:7b", "qwen3-vl:8b-instruct", "qwen3.5:4b", "qwen3.5:9b")


def placement(url: str, model: str) -> str | None:
    """How Ollama split the loaded model between GPU and CPU (e.g. '100% GPU', '14%/86% CPU/GPU')."""
    for m in httpx.get(f"{url}/api/ps", timeout=10).json().get("models", []):
        if m["name"] == model:
            total, vram = m.get("size", 0), m.get("size_vram", 0)
            if not total:
                return None
            gpu = round(100 * vram / total)
            return "100% GPU" if gpu >= 100 else f"{100 - gpu}%/{gpu}% CPU/GPU"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("reports/dev/spike.json"))
    a = ap.parse_args()
    s = settings()
    doc = cord.load(s.data_dir, "validation", limit=1)[0]
    client = Ollama(s.ollama_url, s.request_timeout_s, s.num_ctx, s.max_output_tokens)
    rows = []
    for model in CANDIDATES:
        extractor = VisionExtractor(client, model)
        cold = extractor.extract(doc)
        warm = extractor.extract(doc)
        rows.append(
            {
                "model": model,
                "cold_s": round(cold.seconds, 2),
                "warm_s": round(warm.seconds, 2),
                "placement": placement(s.ollama_url, model),
                "prompt_tokens": warm.prompt_tokens,
                "completion_tokens": warm.completion_tokens,
                "answer": warm.fields,
                "error": warm.error,
            }
        )
        httpx.post(f"{s.ollama_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)  # unload
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "answer"}))
    report = {"document": doc.id, "gold": doc.gold, "runs": rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
