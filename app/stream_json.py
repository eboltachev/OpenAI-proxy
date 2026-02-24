from __future__ import annotations

import json
from typing import Any, AsyncIterator, Protocol


class RedisStreamClient(Protocol):
    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        id: str = "*",
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str: ...

    async def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]: ...

    async def xtrim(self, name: str, maxlen: int, approximate: bool = True) -> int: ...


async def write_response_raw_json(
    redis: RedisStreamClient,
    stream_key: str,
    payload: dict[str, Any],
    *,
    done: bool = False,
    terminal_maxlen: int = 10_000,
) -> str:
    """Write one JSON chunk to a Redis stream.

    Important: we do not trim active streams on each chunk write. Trimming while
    producers are still writing can evict unread IDs and break SSE consumers that
    read strictly by `last_id`.

    If `done=True`, we append the terminal chunk and then trim once to keep
    long-term storage bounded.
    """

    record_id = await redis.xadd(
        stream_key,
        {"json": json.dumps(payload, ensure_ascii=False)},
    )

    if done:
        await redis.xtrim(stream_key, maxlen=terminal_maxlen, approximate=True)

    return record_id


async def iter_stream_json(
    redis: RedisStreamClient,
    stream_key: str,
    *,
    last_id: str = "0-0",
    block_ms: int = 15_000,
    count: int = 100,
) -> AsyncIterator[dict[str, Any]]:
    while True:
        rows = await redis.xread(
            streams={stream_key: last_id},
            block=block_ms,
            count=count,
        )
        if not rows:
            continue

        for _, entries in rows:
            for entry_id, fields in entries:
                raw = fields.get("json")
                if raw is None:
                    last_id = entry_id
                    continue
                last_id = entry_id
                item = json.loads(raw)
                yield item
                if item.get("done") is True:
                    return
