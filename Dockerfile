FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock* /app/

RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev; else uv sync --no-dev; fi

COPY app /app/app

ENV PYTHONUNBUFFERED=1

CMD uv run uvicorn app.main:app --log-level=info --host=${API_HOST} --port=${API_PORT}

