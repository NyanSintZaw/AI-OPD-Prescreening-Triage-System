# Mock hospital HIS — runnable with `docker compose up`, the same way the
# team starts Postgres. SQLite lives inside the container; a fresh container
# auto-seeds the synthetic pre-registration sample.
FROM python:3.11-slim

# uv (matches the project's uv-managed workflow).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . .

# Install runtime deps only (fastapi + uvicorn), from the locked versions.
RUN uv sync --frozen --no-dev

EXPOSE 8001

# --no-dev matches the build above: without it, `uv run` re-syncs the dev group
# (pytest, httpx, …) at container start and needs PyPI access it may not have.
CMD ["uv", "run", "--no-dev", "uvicorn", "his_mock.main:app", "--host", "0.0.0.0", "--port", "8001"]
