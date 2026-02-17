# Dynamic vLLM Proxy (FastAPI)

Прокси-микросервис на FastAPI, который:

- запускается через Docker Compose;
- динамически читает конфиг роутов из bind-mounted `config/routes.yaml` на каждом запросе;
- требует сервисный ключ `PROXY_SECRET_KEY` для любого проксируемого запроса;
- хранит **все upstream-ключи только в конфиге** (не в `environment`).

## Запуск

`.env` (только сервисные переменные):

```env
PROXY_SECRET_KEY=proxy-internal-secret
```

```bash
docker compose up --build -d
```

## Безопасность входа в прокси

Каждый запрос в прокси должен содержать один из вариантов:

```http
X-Proxy-Secret: <PROXY_SECRET_KEY>
```

или

```http
Authorization: Bearer <PROXY_SECRET_KEY>
```

Это нужно для совместимости с OpenAI SDK, где секрет обычно передаётся как `api_key` в `Authorization` заголовке. Иначе `401`.

## Таймаут запроса

Таймаут задается **из входящего запроса**, а не хардкодится в коде:

- query-параметр `timeout` (например `?timeout=60`), или
- header `X-Timeout-Seconds`.

Если таймаут не передан — используется стандартный таймаут `httpx`.

## Конфиг роутеров (`config/routes.yaml`)

Для каждого роута задаются:

- `path`
- `methods`
- `upstream_url`
- `upstream_key`
- `upstream_key_header` (опционально, default `Authorization`)
- `upstream_key_prefix` (опционально, default `Bearer `)

Пример:

```yaml
routes:
  - path: /v1/chat/completions
    methods: [POST]
    upstream_url: http://vllm:8000/v1/chat/completions
    upstream_key: super-secret-chat-key
```

> Любое изменение `config/routes.yaml` подхватывается без перезапуска контейнера. В `docker-compose.yml` монтируется директория `./config`, чтобы замена файла (новый inode) тоже подхватывалась сразу.

## Пример вызова через OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="proxy-internal-secret",  # должен совпадать с PROXY_SECRET_KEY
)

response = client.chat.completions.create(
    model="your-model",
    messages=[{"role": "user", "content": "Привет"}],
)

print(response)
```

### Особенность `/v1/models`

`GET /v1/models` работает как агрегатор: прокси запрашивает `/v1/models` у всех доступных upstream-роутеров (уникальных по хосту+ключу), объединяет ответы и возвращает единый список моделей.

### Особенность `/health`

`GET /health` работает как агрегатор health-check:

- прокси находит все роуты `path: /health` с методом `GET`;
- опрашивает каждый `upstream_url` с его route-specific ключом;
- возвращает агрегированный отчёт по каждому upstream.

## Проверка работы с OpenAI / DeepInfra URL

Сервис совместим с конфигом, где upstream указывает на OpenAI/DeepInfra, если заданы корректные route-specific ключи и заголовки. Пример:

```yaml
routes:
  - path: /v1/chat/completions
    methods: [POST]
    upstream_url: https://api.openai.com/v1/chat/completions
    upstream_key: sk-...
    upstream_key_header: Authorization
    upstream_key_prefix: "Bearer "

  - path: /v1/chat/completions
    methods: [POST]
    upstream_url: https://api.deepinfra.com/v1/openai/chat/completions
    upstream_key: di-...
    upstream_key_header: Authorization
    upstream_key_prefix: "Bearer "
```

## Полный список роутеров из текущего изображения

- `POST /scale_elastic_ep`
- `POST /is_scaling_elastic_ep`
- `POST /tokenize`
- `POST /detokenize`
- `POST /inference/v1/generate`
- `POST /pause`
- `POST /resume`
- `GET /is_paused`
- `GET /metrics`
- `GET /health`
- `GET /load`
- `GET /v1/models`
- `GET /version`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `POST /v1/responses/{response_id}/cancel`
- `POST /v1/messages`
- `POST /v1/chat/completions`
- `POST /v1/completions`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/translations`
- `GET /ping`
- `POST /ping`
- `POST /invocations`
- `POST /classify`
- `POST /v1/embeddings`
- `POST /score`
- `POST /v1/score`
- `POST /rerank`
- `POST /v1/rerank`
- `POST /v2/rerank`
- `POST /pooling`
