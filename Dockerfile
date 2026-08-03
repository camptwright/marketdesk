FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Pinned via COPY --from rather than a curl|sh install step, so the build is
# reproducible and doesn't depend on astral.sh being reachable.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python -e .

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1001 marketdesk

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config

RUN chown -R marketdesk:marketdesk /app
USER marketdesk

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
