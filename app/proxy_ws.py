from __future__ import annotations

import os
from urllib.parse import urlencode

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .config import Upstream
from .upstream import join_upstream_url, tls_verify


def _proxy_token() -> str:
    return os.getenv("PROXY_BEARER_TOKEN", "").strip()


async def proxy_realtime_ws(ws: WebSocket, upstream: Upstream):
    """
    Упрощённая схема:
    - model берём из query (?model=...)
    - upstream WS url строим как base_url + /v1/realtime (+ query без model, если нужно)
    """
    token = _proxy_token()
    if token:
        auth = ws.headers.get("authorization", "")
        ok = auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == token
        if not ok:
            await ws.close(code=4401)
            return

    model = ws.query_params.get("model")
    if not model:
        await ws.close(code=4400)
        return

    # формируем ws/wss url
    http_url = join_upstream_url(upstream.base_url, "/v1/realtime")
    if http_url.startswith("https://"):
        up_ws = "wss://" + http_url[len("https://"):]
    elif http_url.startswith("http://"):
        up_ws = "ws://" + http_url[len("http://"):]
    else:
        up_ws = http_url

    # прокидываем model как query в upstream (это наиболее типичный паттерн realtime)
    q = dict(ws.query_params)
    q["model"] = upstream.model
    up_ws = up_ws + "?" + urlencode(q)

    extra_headers = {}
    if upstream.api_key:
        extra_headers["Authorization"] = f"Bearer {upstream.api_key}"

    await ws.accept()

    ssl_verify = tls_verify()

    try:
        async with websockets.connect(up_ws, extra_headers=extra_headers, ssl=ssl_verify if up_ws.startswith("wss://") else None) as up:
            async def c2u():
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if "text" in msg and msg["text"] is not None:
                        await up.send(msg["text"])
                    elif "bytes" in msg and msg["bytes"] is not None:
                        await up.send(msg["bytes"])

            async def u2c():
                async for msg in up:
                    if isinstance(msg, (bytes, bytearray)):
                        await ws.send_bytes(bytes(msg))
                    else:
                        await ws.send_text(str(msg))

            import asyncio
            await asyncio.gather(c2u(), u2c())
    except WebSocketDisconnect:
        return
    except Exception:
        await ws.close(code=1011)

