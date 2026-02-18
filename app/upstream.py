from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx

from .config import Upstream


@dataclass
class UpstreamCaps:
    paths: set[str] | None

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
        return UpstreamCaps(paths=None)

def tls_verify() -> bool:
    v = os.getenv("API_TLS_VERIFY", "1").strip().lower()
    return v not in ("0", "false", "no", "off")

def timeout_s() -> float:
    try:
        return float(os.getenv("API_UPSTREAM_TIMEOUT", "600"))
    except Exception:
        return 600.0

def allow_ssl_downgrade() -> bool:
    v = os.getenv("API_ALLOW_SSL_DOWNGRADE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")

def join_upstream_url(base_url: str, incoming_path: str) -> str:
    base = base_url.rstrip("/")
    path = incoming_path if incoming_path.startswith("/") else "/" + incoming_path
    if (base.endswith("/v1") or base.endswith("/v1/openai")) and path.startswith("/v1/"):
        path = path[len("/v1"):]
    return base + path

def http_fallback_url_on_ssl_error(url: str, err: Exception) -> str | None:
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


caps_cache = CapsCache()
