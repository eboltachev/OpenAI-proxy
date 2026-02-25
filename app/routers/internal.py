from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..errors import openai_error
from ..stream_json import iter_stream_json

router = APIRouter()


@router.get("/internal/streams/{stream_key}")
async def stream_from_redis(request: Request, stream_key: str):
    redis_client = getattr(request.app.state, "redis_stream_client", None)
    if redis_client is None:
        return openai_error(503, "Redis stream client is not configured", code="redis_not_configured")

    async def sse_iter():
        async for item in iter_stream_json(redis_client, stream_key):
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(sse_iter(), media_type="text/event-stream")
