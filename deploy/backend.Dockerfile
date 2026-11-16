FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias de compute-py
COPY backend/compute-py/pyproject.toml ./backend/compute-py/pyproject.toml
RUN uv sync --project /app/backend/compute-py --no-dev

# Dependencias de nisar-harness (para corridas bajo demanda)
COPY nisar-harness/pyproject.toml nisar-harness/uv.lock ./nisar-harness/
RUN uv sync --project /app/nisar-harness --frozen --no-dev

# Código y configuración necesarios en runtime (ver settings.py)
COPY backend/shared/schemas ./backend/shared/schemas
COPY frontend/src/assets/config ./frontend/src/assets/config
COPY alert-harness ./alert-harness
COPY nisar-harness ./nisar-harness
COPY backend/compute-py/src ./backend/compute-py/src

RUN mkdir -p /app/data/raw/firms /app/data/raw/precip /app/data/processed/cog /app/data/manifests \
             /app/alert-harness/output/alerts /app/alert-harness/output/monitor \
             /app/nisar-harness/output

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["/app/backend/compute-py/.venv/bin/uvicorn", "main:app", "--app-dir", "/app/backend/compute-py/src", "--host", "0.0.0.0", "--port", "8000"]
