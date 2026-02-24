import asyncio
import unittest

from app.main import app, stream_from_redis
from app.proxy_http import _mirror_sse_chunks_to_redis


class FakeRedis:
    def __init__(self):
        self.writes = []
        self.reads = []

    async def xadd(self, name, fields, id="*", maxlen=None, approximate=True):
        self.writes.append((name, fields, maxlen, approximate))
        return f"{len(self.writes)}-0"

    async def xtrim(self, name, maxlen, approximate=True):
        self.writes.append((name, {"trim": True}, maxlen, approximate))
        return 1

    async def xread(self, streams, count=None, block=None):
        if not self.reads:
            return []
        return [self.reads.pop(0)]


class StreamJsonUsageTests(unittest.TestCase):
    def test_proxy_http_mirrors_sse_chunks_to_redis(self):
        redis = FakeRedis()

        async def upstream_iter():
            yield b"data: first\\n\\n"
            yield b"data: second\\n\\n"

        async def collect():
            out = []
            async for chunk in _mirror_sse_chunks_to_redis(upstream_iter(), redis, "resp:42"):
                out.append(chunk)
            return out

        chunks = asyncio.run(collect())

        self.assertEqual(chunks, [b"data: first\\n\\n", b"data: second\\n\\n"])
        self.assertEqual(redis.writes[0][0], "resp:42")
        self.assertEqual(redis.writes[1][0], "resp:42")
        self.assertEqual(redis.writes[2], ("resp:42", {"json": "{\"done\": true}"}, None, True))
        self.assertEqual(redis.writes[3], ("resp:42", {"trim": True}, 10_000, True))

    def test_main_internal_stream_endpoint_consumes_iter_stream_json(self):
        redis = FakeRedis()
        redis.reads = [
            ("resp:77", [("1-0", {"json": '{"delta":"a"}'}), ("2-0", {"json": '{"done": true}'})]),
        ]
        app.state.redis_stream_client = redis

        async def collect():
            resp = await stream_from_redis("resp:77")
            items = []
            async for part in resp.body_iterator:
                items.append(part)
            return items

        body_parts = asyncio.run(collect())
        self.assertEqual(body_parts, [b'data: {"delta": "a"}\n\n', b'data: {"done": true}\n\n'])


if __name__ == "__main__":
    unittest.main()
