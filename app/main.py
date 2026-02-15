from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

ROUTES_CONFIG_PATH = Path(os.getenv("ROUTES_CONFIG_PATH", "/app/config/routes.yaml"))
PROXY_SECRET_KEY = os.getenv("PROXY_SECRET_KEY")

app = FastAPI(title="Dynamic vLLM Proxy", version="1.2.0")


class ConfigError(RuntimeError):
    """Ошибка чтения/валидации конфигурации."""


@dataclass(frozen=True)
class RouteConfig:
    path: str
    path_regex: re.Pattern[str]
    methods: list[str]
    upstream_url: str
    upstream_key: str
    upstream_key_header: str
    upstream_key_prefix: str


def _compile_path_pattern(path: str) -> re.Pattern[str]:
    # /v1/responses/{response_id} -> ^/v1/responses/(?P<response_id>[^/]+)$
    pattern = re.sub(r"\{([^/{}]+)\}", r"(?P<\1>[^/]+)", path)
    return re.compile(rf"^{pattern}$")


def _load_routes_config() -> list[RouteConfig]:
    if not ROUTES_CONFIG_PATH.exists():
        raise ConfigError(f"Config file not found: {ROUTES_CONFIG_PATH}")

    try:
        data = yaml.safe_load(ROUTES_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {ROUTES_CONFIG_PATH}: {exc}") from exc

    routes = data.get("routes")
    if not isinstance(routes, list):
        raise ConfigError("Config must contain list field 'routes'.")

    normalized: list[RouteConfig] = []
    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            raise ConfigError(f"routes[{idx}] must be object.")

        path = route.get("path")
        methods = route.get("methods", ["GET"])
        upstream_url = route.get("upstream_url")
        upstream_key = route.get("upstream_key")
        upstream_key_header = route.get("upstream_key_header", "Authorization")
        upstream_key_prefix = route.get("upstream_key_prefix", "Bearer ")

        if not isinstance(path, str) or not path.startswith("/"):
            raise ConfigError(f"routes[{idx}].path must be absolute path string.")
        if not isinstance(methods, list) or not methods or not all(isinstance(m, str) for m in methods):
            raise ConfigError(f"routes[{idx}].methods must be non-empty string list.")
        if not isinstance(upstream_url, str) or not upstream_url.startswith(("http://", "https://")):
            raise ConfigError(f"routes[{idx}].upstream_url must be absolute URL string.")
        if not isinstance(upstream_key, str) or not upstream_key.strip():
            raise ConfigError(f"routes[{idx}].upstream_key must be non-empty string.")
        if not isinstance(upstream_key_header, str) or not upstream_key_header.strip():
            raise ConfigError(f"routes[{idx}].upstream_key_header must be non-empty string.")
        if not isinstance(upstream_key_prefix, str):
            raise ConfigError(f"routes[{idx}].upstream_key_prefix must be string.")

        normalized.append(
            RouteConfig(
                path=path,
                path_regex=_compile_path_pattern(path),
                methods=[m.upper() for m in methods],
                upstream_url=upstream_url,
                upstream_key=upstream_key,
                upstream_key_header=upstream_key_header,
                upstream_key_prefix=upstream_key_prefix,
            )
        )
    return normalized


def _resolve_route(path: str, method: str) -> tuple[RouteConfig, dict[str, str]] | None:
    for route in _load_routes_config():
        match = route.path_regex.match(path)
        if match and method.upper() in route.methods:
            return route, match.groupdict()
    return None


def _validate_proxy_secret(secret_header: str | None) -> None:
    if not PROXY_SECRET_KEY:
        raise HTTPException(status_code=500, detail="PROXY_SECRET_KEY is not set in environment")
    if secret_header != PROXY_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Proxy-Secret")


def _build_proxy_headers(request_headers: Any, route: RouteConfig) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request_headers.items()
        if key.lower() not in {"host", "content-length", "x-proxy-secret"}
    }
    headers[route.upstream_key_header] = f"{route.upstream_key_prefix}{route.upstream_key}"
    return headers


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_request(
    full_path: str,
    request: Request,
    x_proxy_secret: str | None = Header(default=None),
) -> Response:
    _validate_proxy_secret(x_proxy_secret)
    incoming_path = "/" + full_path

    try:
        resolved = _resolve_route(incoming_path, request.method)
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if resolved is None:
        raise HTTPException(status_code=404, detail="Route is not enabled by current config")

    route, path_params = resolved

    try:
        upstream_url = route.upstream_url.format(**path_params)
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing upstream_url template var: {exc}") from exc

    body = await request.body()
    query_params = list(request.query_params.multi_items())
    headers = _build_proxy_headers(request.headers, route)

    async with httpx.AsyncClient(timeout=300) as client:
        upstream_response = await client.request(
            method=request.method,
            url=upstream_url,
            params=query_params,
            content=body,
            headers=headers,
        )

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
    }

    content_type = upstream_response.headers.get("content-type", "")
    if "application/json" in content_type:
        return JSONResponse(
            status_code=upstream_response.status_code,
            content=upstream_response.json(),
            headers=response_headers,
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=content_type or None,
    )
