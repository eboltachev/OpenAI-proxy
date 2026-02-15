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

Каждый запрос в прокси должен содержать:

```http
X-Proxy-Secret: <PROXY_SECRET_KEY>
```

Иначе `401`.

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

> Любое изменение `config/routes.yaml` подхватывается без перезапуска контейнера.

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
