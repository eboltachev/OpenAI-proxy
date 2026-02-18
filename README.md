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
- `cp .config/example.sources.yml .config/sources.yml`

## Run
```bash
docker compose up --build -d
```



## Logging
- Асинхронное логирование в stdout включено по умолчанию.
- Формат сообщения: `datetime module action result ...` (с доп. полями контекста).
- Уровень логирования задаётся через `API_LOG_LEVEL` (например, `INFO`, `WARNING`, `ERROR`).
