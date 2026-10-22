# The extraction worker: locked dependencies from uv.lock, non-root, no build tools in the final stage.
# Models run in Ollama on the host (VDE_OLLAMA_URL); the RapidOCR models ship inside the rapidocr wheel.
FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.12.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev --extra worker --extra ocr
COPY src ./src
RUN uv sync --locked --no-dev --extra worker --extra ocr

FROM python:3.12.12-slim
# Debian security fixes published after the base image was built, and the libraries OpenCV (RapidOCR) loads
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home vde
WORKDIR /app
COPY --from=build --chown=vde:vde /app /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER vde
EXPOSE 9108
# healthy while the poll loop is alive: it touches the heartbeat file before every long-poll
HEALTHCHECK --interval=15s --timeout=3s --retries=4 \
  CMD ["python", "-c", "import os, sys, time; sys.exit(0 if time.time() - os.path.getmtime('/tmp/vde-worker-heartbeat') < 60 else 1)"]
CMD ["vde", "worker"]
