from __future__ import annotations

from fastapi import APIRouter, WebSocket

from ..config import ConfigProvider
from ..proxy_ws import proxy_realtime_ws

router = APIRouter()


@router.websocket("/v1/realtime")
async def realtime(ws: WebSocket):
    provider: ConfigProvider = ws.app.state.config_provider
    cfg = provider.get()
    model = ws.query_params.get("model")
    if not model or model not in cfg:
        await ws.close(code=4404)
        return
    await proxy_realtime_ws(ws, cfg[model])
