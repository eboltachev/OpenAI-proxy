# vLLM / Ollama / DeepInfra OpenAI Proxy

## Что это
Прокси, который:
- агрегирует модели из YAML в `GET /v1/models`
- проверяет Bearer token на вход
- роутит любой запрос по `model` на нужный upstream
- поддерживает streaming request/response и большие multipart (audio/*)
- лимитирует размер body (413)

## Быстрый старт
1) Скопируй примеры:
- `cp .env.example .env`
- `cp config/models.example.yml config/models.yml`

2) Подними:
```bash
docker compose up --build -d

