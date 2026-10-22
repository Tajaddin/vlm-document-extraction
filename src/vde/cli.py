"""`vde` command line: data, evaluation runs and the summary table."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer

from vde import log
from vde.config import settings
from vde.documents import Document

app = typer.Typer(no_args_is_help=True, add_completion=False)
Dataset = Literal["cord", "fatura"]

# The fixed document sets. Changing a seed changes which documents are scored, so they are constants, not options.
FATURA_TEST_PER_LAYOUT, FATURA_TEST_SEED = 10, 2026
FATURA_DEV_SEED, FATURA_EXAMPLE_SEED, EXAMPLE_SHUFFLE_SEED = 11, 7, 3


@app.callback()
def main() -> None:
    log.configure(settings().log_level)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def documents(dataset: Dataset, split: Literal["dev", "test"], limit: int | None = None) -> list[Document]:
    """CORD: dev = validation, test = test. FATURA: test = 10 documents from each of the 10 held-out layouts;
    dev = 1 document from each of the 40 training layouts."""
    from vde.data import cord
    from vde.data.fatura import Fatura

    data_dir = settings().data_dir
    if dataset == "cord":
        docs = cord.load(data_dir, "validation" if split == "dev" else "test")
    elif split == "test":
        docs = Fatura(data_dir).sample("test", FATURA_TEST_PER_LAYOUT, FATURA_TEST_SEED)
    else:
        docs = Fatura(data_dir).sample("train", 1, FATURA_DEV_SEED)
    return docs[:limit] if limit else docs


def examples(dataset: Dataset, k: int, exclude: set[str]) -> list[Document]:
    """k labelled examples that are never scored: CORD validation receipts, or FATURA training-layout invoices from
    k different layouts. Chosen with a fixed seed, not by hand."""
    if k == 0:
        return []
    from vde.data import cord
    from vde.data.fatura import Fatura

    data_dir = settings().data_dir
    pool = (
        cord.load(data_dir, "validation")
        if dataset == "cord"
        else Fatura(data_dir).sample("train", 1, FATURA_EXAMPLE_SEED)
    )
    pool = [d for d in pool if d.id not in exclude]
    random.Random(EXAMPLE_SHUFFLE_SEED).shuffle(pool)
    return pool[:k]


@app.command()
def fetch(only: Annotated[str | None, typer.Option(help="cord or fatura; both when omitted")] = None) -> None:
    """Download CORD v2 and FATURA and check them against the publishers' checksums."""
    from vde.data.manifest import fetch as do_fetch

    typer.echo(json.dumps(do_fetch(settings().data_dir, only=only), indent=2))


@app.command()
def verify(only: Annotated[str | None, typer.Option(help="cord or fatura; both when omitted")] = None) -> None:
    """Check the downloaded files against the manifest; exit 1 if any is missing or differs."""
    from vde.data.manifest import verify as do_verify

    rows = do_verify(settings().data_dir, only=only)
    typer.echo(json.dumps(rows, indent=2))
    ok = all(r["present"] and all(v for k, v in r.items() if k.endswith("_ok")) for r in rows)
    raise typer.Exit(0 if ok else 1)


@app.command("data-report")
def data_report(out: Annotated[Path, typer.Option()] = Path("reports/data/fatura-gold.json")) -> None:
    """How often each FATURA gold field parses from the annotation text, over all 10,000 invoices."""
    from vde.data.fatura import Fatura, parse_report

    fatura = Fatura(settings().data_dir)
    result = {"layouts": fatura.layouts, **parse_report(fatura)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    typer.echo(json.dumps(result["fields"], indent=2))


@app.command("eval")
def evaluate(
    dataset: Annotated[str, typer.Option(help="cord or fatura")],
    approach: Annotated[str, typer.Option(help="vlm, ocr, vertex or fake")] = "vlm",
    model: Annotated[str | None, typer.Option(help="Ollama model; defaults to VDE_VLM_MODEL / VDE_TEXT_MODEL")] = None,
    split: Annotated[str, typer.Option(help="dev (prompt work) or test (scored once)")] = "test",
    shots: Annotated[int, typer.Option(help="few-shot examples")] = 0,
    variant: Annotated[str, typer.Option(help="receipt schema: required or optional")] = "required",
    limit: Annotated[int | None, typer.Option()] = None,
    name: Annotated[str | None, typer.Option(help="run name; default from the options")] = None,
    out_dir: Annotated[Path, typer.Option()] = Path("reports/eval"),
) -> None:
    from vde import evaluate as ev
    from vde.extract.fake import FakeExtractor
    from vde.extract.ollama import Ollama, VisionExtractor

    if dataset not in ("cord", "fatura") or split not in ("dev", "test") or variant not in ("required", "optional"):
        raise typer.BadParameter("dataset cord|fatura, split dev|test, variant required|optional")
    s = settings()
    docs = documents(dataset, split, limit)  # type: ignore[arg-type]
    shown = examples(dataset, shots, {d.id for d in docs})  # type: ignore[arg-type]
    client = Ollama(s.ollama_url, s.request_timeout_s, s.num_ctx, s.max_output_tokens)
    if approach == "vlm":
        model = model or s.vlm_model
        extractor: ev.Extractor = VisionExtractor(client, model, shown, variant)  # type: ignore[arg-type]
    elif approach == "ocr":
        from vde.extract.ocr import OcrLlmExtractor

        model = model or s.text_model
        if shots:
            raise typer.BadParameter("the OCR baseline runs zero-shot")
        extractor = OcrLlmExtractor(client, model, variant)  # type: ignore[arg-type]
    elif approach == "vertex":  # bills VDE_VERTEX_PROJECT; see docs/DEPLOY.md
        from vde.extract.vertex import VertexExtractor

        if shots:
            raise typer.BadParameter("the Vertex AI extractor runs zero-shot")
        vertex = VertexExtractor.from_settings(s)
        model = vertex.model
        extractor = vertex
    elif approach == "fake":
        model = "fake"
        extractor = FakeExtractor()
    else:
        raise typer.BadParameter("approach vlm|ocr|vertex|fake")
    run_name = name or f"{approach}-{model.replace(':', '-').replace('/', '-')}-{shots}shot" + (
        f"-{variant}" if dataset == "cord" else ""
    )
    folder = out_dir / f"{dataset}-{split}"
    rows = ev.run(extractor, docs, folder / f"{run_name}.predictions.jsonl")
    config = {
        "dataset": dataset,
        "split": split,
        "approach": approach,
        "model": model,
        "shots": shots,
        "receipt_schema": variant if dataset == "cord" else None,
        "num_ctx": s.num_ctx,
        "max_output_tokens": s.max_output_tokens,
        "temperature": 0,
        "environment": ev.environment(s.ollama_url if approach != "fake" else None),
    }
    result = ev.report(run_name, docs, rows, config, shown)
    (folder / f"{run_name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k not in ("per_document", "document_ids", "fields", "config")}
    typer.echo(json.dumps(summary, indent=2))


@app.command()
def summarize(out_dir: Annotated[Path, typer.Option()] = Path("reports/eval")) -> None:
    """One table per dataset and split from every committed report."""
    lines = []
    for folder in sorted(p for p in out_dir.iterdir() if p.is_dir()):
        reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]
        if not reports:
            continue
        lines += [
            f"## {folder.name}",
            "",
            "| run | docs | field F1 (95% CI) | second metric | p50 s | p95 s | errors |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in sorted(reports, key=lambda r: -r["field_f1"]):
            second = (
                f"TED acc {r['ted_accuracy']:.3f}"
                if r["kind"] == "receipt"
                else f"fully correct {r['documents_fully_correct']:.2f}"
            )
            lat = r["latency"]
            ci = r["field_f1_95ci"]
            lines.append(
                f"| {r['run']} | {r['documents']} | {r['field_f1']:.3f} ({ci[0]:.3f}-{ci[1]:.3f}) | {second} | {lat['p50_s']} | {lat['p95_s']} | {sum(r['errors'].values())} |"
            )
        lines.append("")
    text = "\n".join(lines)
    (out_dir / "SUMMARY.md").write_text(
        "# Evaluation summary\n\nGenerated by `vde summarize`.\n\n" + text + "\n", encoding="utf-8", newline="\n"
    )
    typer.echo(text)


@app.command()
def worker() -> None:
    """Consume extraction jobs from the intake queue (VDE_QUEUE_URL) until stopped."""
    from vde.worker.app import build

    build(settings()).run()
