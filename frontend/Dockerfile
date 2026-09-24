# The standalone chat UI, as a container. It talks to a deployed Agent Runtime engine, never to BigQuery directly:
# the engine's runtime identity is what reads the store data, and this service only needs to be allowed to call it.
#
#   make deploy-frontend ENV=dev        # builds this and deploys it to Cloud Run
#
# Built from the repository root (the server imports agents/ for its types), so the build context is the repo.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependencies first, so a code change does not re-resolve them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY agents ./agents
COPY frontend ./frontend
COPY deployment ./deployment
COPY README.md ./README.md
RUN uv sync --locked --no-dev

# Cloud Run sets PORT and reaches the container from outside it, so the server binds 0.0.0.0 when PORT is set.
ENV PYTHONUNBUFFERED=1
CMD ["uv", "run", "python", "frontend/server.py", "--target", "agent-engine"]
