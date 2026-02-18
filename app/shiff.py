from __future__ import annotations

import os
import re
from typing import AsyncIterator, Tuple

from fastapi import Request

_JSON_MODEL_RE = re.compile(rb'"model"\s*:\s*"([^"\\]+)"')
_MP_MODEL_RE = re.compile(rb'name="model"\r\n\r\n([^\r\n]+)')


def sniff_limit() -> int:
    try:
        return int(os.getenv("API_SNIFF_BYTES", "1048576"))
    except Exception:
        return 1048576

async def sniff_model_and_stream(request: Request) -> Tuple[str, AsyncIterator[bytes]]:
    qp_model = request.query_params.get("model")
    if qp_model:
        async def body_iter_qp():
            async for chunk in request.stream():
                yield chunk
        return qp_model, body_iter_qp()
    limit = sniff_limit()
    content_type = (request.headers.get("content-type") or "").lower()
    aiter = request.stream()
    seen_chunks: list[bytes] = []
    prefix = bytearray()
    model: str | None = None
    async for chunk in aiter:
        if chunk:
            seen_chunks.append(chunk)
            if len(prefix) < limit:
                prefix.extend(chunk[: max(0, limit - len(prefix))])
            model = _extract_model_from_prefix(bytes(prefix), content_type)
            if model:
                break
            if len(prefix) >= limit:
                break
    if not model:
        raise ValueError("Model is not found in request body (sniff limit exceeded or missing).")
    async def body_iter():
        for c in seen_chunks:
            yield c
        async for rest in aiter:
            yield rest
    return model, body_iter()

def _extract_model_from_prefix(prefix: bytes, content_type: str) -> str | None:
    if "application/json" in content_type or content_type.endswith("+json"):
        m = _JSON_MODEL_RE.search(prefix)
        return m.group(1).decode("utf-8", "ignore") if m else None
    if "multipart/form-data" in content_type:
        m = _MP_MODEL_RE.search(prefix)
        return m.group(1).decode("utf-8", "ignore").strip() if m else None
    m = _JSON_MODEL_RE.search(prefix)
    return m.group(1).decode("utf-8", "ignore") if m else None
