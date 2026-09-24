FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev
COPY agents ./agents
COPY services ./services
COPY deployment ./deployment
COPY frontend ./frontend
COPY README.md ./README.md
RUN uv sync --locked --no-dev
CMD ["sh", "-c", "exec .venv/bin/uvicorn services.store_events.worker:app --host 0.0.0.0 --port ${PORT:-8080}"]
