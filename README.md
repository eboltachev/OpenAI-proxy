# vLLM / Ollama / Other OpenAI Proxy

## Description
Прокси, который:
- агрегирует модели из YAML в `GET /v1/models`
- проверяет Bearer token на вход
- роутит любой запрос по `model` на нужный upstream
- поддерживает streaming request/response и большие multipart (audio/*)
- лимитирует размер body (413)

## Configuration
- `cp .env.example .env`
- `cp example.config.yml .config.yml`

## Run
```bash
docker compose up --build -d
```

