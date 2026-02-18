import asyncio
import unittest

from app.async_logger import AsyncActionLogger


class AsyncActionLoggerLoopBindingTests(unittest.TestCase):
    def test_rebinds_queue_across_event_loops(self):
        logger = AsyncActionLogger()

        async def lifecycle() -> None:
            await logger.start()
            await logger.log("tests.async_logger", "lifecycle", "ok")
            await logger.stop()

        asyncio.run(lifecycle())
        asyncio.run(lifecycle())

    def test_log_is_safe_before_start(self):
        logger = AsyncActionLogger()

        async def log_once() -> None:
            await logger.log("tests.async_logger", "prestart", "ok")

        asyncio.run(log_once())


if __name__ == "__main__":
    unittest.main()
