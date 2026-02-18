from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class Upstream:
    model: str
    base_url: str
    api_key: str


def config_path() -> str:
    return os.getenv("API_CONFIG_PATH", "/app/.config.yml")


def load_config() -> dict[str, Upstream]:
    path = config_path()
    with open(path, "r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
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
