FROM python:3.13-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY README.md ./README.md
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Call uvicorn/arq from the already-installed venv directly, rather than "uv run" -- uv run
# re-syncs against pyproject's dependency-groups on every invocation, which pulls in
# dev-only tools like ruff at container startup even though --no-dev was used above.
ENV PATH="/app/.venv/bin:$PATH"

# Overridden by docker-compose.yml's "worker" service to run the arq worker instead.
CMD uvicorn asyncjobs.main:app --host 0.0.0.0 --port 8000
