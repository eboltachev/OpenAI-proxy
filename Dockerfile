FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

RUN groupadd --system app && useradd --system --gid app --create-home --home /home/app app

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock* /app/

RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev; else uv sync --no-dev; fi

COPY app /app/app

RUN chown -R app:app /app

USER app

CMD uv run uvicorn app.main:app --log-level=info --host=${API_HOST} --port=${API_PORT}
