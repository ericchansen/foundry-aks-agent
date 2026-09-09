FROM ghcr.io/astral-sh/uv:0.11.0 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && chown -R 10001:10001 /app

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "foundry_aks_agent.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
