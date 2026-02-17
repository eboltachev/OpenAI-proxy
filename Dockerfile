FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1
ENV ROUTES_CONFIG_PATH=/app/config/routes.yaml

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
