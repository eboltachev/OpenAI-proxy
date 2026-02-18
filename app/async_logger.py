from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class _LogEvent:
    level: int
    module: str
    action: str
    result: str
    details: dict[str, Any]


class AsyncActionLogger:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[_LogEvent | None] = asyncio.Queue(maxsize=1000)
        self._worker_task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger("openai_proxy")
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(_log_level())
        self._logger.propagate = False

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(), name="openai-proxy-async-logger")

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None

    async def log(self, module: str, action: str, result: str, *, level: int = logging.INFO, **details: Any) -> None:
        event = _LogEvent(level=level, module=module, action=action, result=result, details=details)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._logger.warning(self._format_event(event, dropped=True))

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            with contextlib.suppress(Exception):
                self._logger.log(event.level, self._format_event(event))

    def _format_event(self, event: _LogEvent, dropped: bool = False) -> str:
        ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        payload = {
            "datetime": ts,
            "module": event.module,
            "action": event.action,
            "result": event.result,
            **event.details,
        }
        if dropped:
            payload["warning"] = "log_queue_full"
        return " ".join(f"{k}={_safe_value(v)}" for k, v in payload.items())


def _safe_value(v: Any) -> str:
    text = str(v).replace("\n", " ").strip()
    return f'"{text}"' if (" " in text or "=" in text or not text) else text


def _log_level() -> int:
    raw = os.getenv("API_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


async_logger = AsyncActionLogger()
