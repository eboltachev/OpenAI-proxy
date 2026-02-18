from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx

from .config import Upstream


def tls_verify() -> bool:
    v = os.getenv("PROXY_TLS_VERIFY", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def timeout_s() -> float:
    try:
        return float(os.getenv("PROXY_UPSTREAM_TIMEOUT", "600"))
    except Exception:
        return 600.0


def allow_ssl_downgrade() -> bool:
    v = os.getenv("PROXY_ALLOW_SSL_DOWNGRADE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def join_upstream_url(base_url: str, incoming_path: str) -> str:
    """
    Нормализация:
    - vLLM: base_url = http://host:port  -> upstream = base_url + incoming_path (/v1/...)
    - DeepInfra: base_url = https://.../v1/openai -> upstream = base_url + (incoming_path без /v1)
    - Ollama: base_url может быть http://host:11434 или http://host:11434/v1
    """
    base = base_url.rstrip("/")
    path = incoming_path if incoming_path.startswith("/") else "/" + incoming_path

    # если upstream уже "внутри /v1" (Ollama /v1 или DeepInfra /v1/openai),
    # а входящий path начинается с /v1/ — выкидываем префикс /v1
    if (base.endswith("/v1") or base.endswith("/v1/openai")) and path.startswith("/v1/"):
        path = path[len("/v1"):]  # оставляем ведущий "/..."

    return base + path


def http_fallback_url_on_ssl_error(url: str, err: Exception) -> str | None:
    """
    Если upstream сконфигурирован как https://, но реально слушает plain HTTP,
    httpx падает с SSL-ошибкой (например `record layer failure`).

    В таком случае возвращаем тот же URL, но с http://, чтобы сделать 1 ретрай.
    """
    if not allow_ssl_downgrade():
        return None

    parts = urlsplit(url)
    if parts.scheme != "https":
        return None

    msg = str(err).lower()
    ssl_markers = (
        "record layer failure",
        "wrong version number",
        "tlsv1 alert",
        "ssl",
    )
    if not any(marker in msg for marker in ssl_markers):
        return None

    return urlunsplit(("http", parts.netloc, parts.path, parts.query, parts.fragment))


@dataclass
class UpstreamCaps:
    paths: set[str] | None  # None => неизвестно, используем allow-list


class CapsCache:
    def __init__(self, ttl_s: float = 60.0):
        self.ttl_s = ttl_s
        self._cache: dict[str, tuple[float, UpstreamCaps]] = {}

    async def get(self, u: Upstream) -> UpstreamCaps:
        now = time.time()
        cached = self._cache.get(u.base_url)
        if cached and (now - cached[0]) < self.ttl_s:
            return cached[1]

        caps = await self._discover(u)
        self._cache[u.base_url] = (now, caps)
        return caps

    async def _discover(self, u: Upstream) -> UpstreamCaps:
        # Пытаемся OpenAPI (vLLM обычно отдаёт /openapi.json)
        url = join_upstream_url(u.base_url, "/openapi.json")
        headers = {}
        if u.api_key:
            headers["Authorization"] = f"Bearer {u.api_key}"

        try:
            async with httpx.AsyncClient(timeout=timeout_s(), verify=tls_verify()) as client:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    j: dict[str, Any] = r.json()
                    paths = set((j.get("paths") or {}).keys())
                    return UpstreamCaps(paths=paths)
        except Exception:
            pass

        # неизвестно — вернём None (дальше решим по allow-list)
        return UpstreamCaps(paths=None)


caps_cache = CapsCache()
