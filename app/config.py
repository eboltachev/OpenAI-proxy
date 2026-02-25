from __future__ import annotations

import os
import time
from typing import Any
from pathlib import Path
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Upstream:
    model: str
    base_url: str
    api_key: str


def config_path() -> str:
    raw_path = os.getenv("API_CONFIG_PATH", "/app/config/example.models.yml")
    return str(Path(raw_path).resolve(strict=False))


def _parse_config(data: dict[str, Any]) -> dict[str, Upstream]:
    models = data.get("models") or []
    out: dict[str, Upstream] = {}
    for item in models:
        model = str(item.get("model", "")).strip()
        base_url = str(item.get("base_url", "")).strip().rstrip("/")
        api_key = str(item.get("api_key", "")).strip()
        if not model or not base_url:
            continue
        if model in out:
            raise ValueError(f"Duplicate model in config: {model}")
        out[model] = Upstream(model=model, base_url=base_url, api_key=api_key)
    return out


def load_config() -> dict[str, Upstream]:
    path = config_path()
    with open(path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    return _parse_config(data)


class ConfigProvider:
    def __init__(self, ttl_s: float = 1.0) -> None:
        self.ttl_s = ttl_s
        self._cached: dict[str, Upstream] | None = None
        self._loaded_at: float = 0.0
        self._mtime: float | None = None

    def get(self) -> dict[str, Upstream]:
        path = config_path()
        stat_mtime = Path(path).stat().st_mtime
        now = time.time()
        if self._cached is not None:
            fresh_by_ttl = (now - self._loaded_at) < self.ttl_s
            same_file = self._mtime == stat_mtime
            if fresh_by_ttl and same_file:
                return self._cached

        with open(path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        parsed = _parse_config(data)
        self._cached = parsed
        self._loaded_at = now
        self._mtime = stat_mtime
        return parsed


def config_cache_ttl_s() -> float:
    try:
        return float(os.getenv("API_CONFIG_CACHE_TTL", "1"))
    except Exception:
        return 1.0
