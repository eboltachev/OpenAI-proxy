# vLLM / Ollama / Other OpenAI Proxy

## Description
Прокси, который:
- агрегирует модели из YAML в `GET /v1/models`
- проверяет Bearer token на вход (HTTP и WebSocket)
- роутит запросы по `model` на нужный upstream
- поддерживает streaming request/response и большие multipart (audio/*)
- лимитирует размер body (413)

## Configuration
- `cp example.env .env`
- `cp config/example.models.yml config/models.yml`
- при необходимости укажите `API_CONFIG_PATH` (по умолчанию читается `/app/config/example.models.yml`)

## Run
```bash
docker compose up --build -d
```

## Tests
```bash
make test
```

## Quality checks
```bash
make check
```


## Security profile
- `API_AUTH_REQUIRED=1` (по умолчанию): требует непустой `API_BEARER_TOKEN`.
- `API_ALLOW_SSL_DOWNGRADE=0` по умолчанию; при включении используйте `API_SSL_DOWNGRADE_ALLOWLIST` (CSV хостов).
- `API_PUBLIC_HEALTH_DETAILS=0` по умолчанию для минимизации раскрытия данных.
- Для приватного доступа доступен `GET /internal/health` (под Bearer auth).

## Logging
- Асинхронное логирование в stdout включено по умолчанию.
- Формат сообщения: `datetime module action result ...` (с доп. полями контекста).
- Уровень логирования задаётся через `API_LOG_LEVEL` (например, `INFO`, `WARNING`, `ERROR`).
