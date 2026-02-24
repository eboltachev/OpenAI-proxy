import asyncio

from app.stream_json import iter_stream_json, write_response_raw_json


class FakeRedis:
    def __init__(self):
        self.xadd_calls = []
        self.xtrim_calls = []
        self._reads = []

    async def xadd(self, name, fields, id="*", maxlen=None, approximate=True):
        self.xadd_calls.append(
            {
                "name": name,
                "fields": fields,
                "id": id,
                "maxlen": maxlen,
                "approximate": approximate,
            }
        )
        return "1-0"

    async def xtrim(self, name, maxlen, approximate=True):
        self.xtrim_calls.append({"name": name, "maxlen": maxlen, "approximate": approximate})
        return 1

    async def xread(self, streams, count=None, block=None):
        if not self._reads:
            return []
        return [self._reads.pop(0)]


def test_write_response_raw_json_does_not_trim_while_stream_active():
    redis = FakeRedis()

    asyncio.run(write_response_raw_json(redis, "resp:1", {"delta": "a"}))

    assert len(redis.xadd_calls) == 1
    assert redis.xadd_calls[0]["maxlen"] is None
    assert redis.xtrim_calls == []


def test_write_response_raw_json_trims_once_after_done():
    redis = FakeRedis()

    asyncio.run(write_response_raw_json(redis, "resp:1", {"done": True}, done=True, terminal_maxlen=321))

    assert len(redis.xadd_calls) == 1
    assert redis.xtrim_calls == [{"name": "resp:1", "maxlen": 321, "approximate": True}]


def test_iter_stream_json_tracks_last_id_and_stops_on_done():
    redis = FakeRedis()
    redis._reads = [
        ("resp:1", [("1-0", {"json": '{"delta":"a"}'}), ("2-0", {"json": '{"done": true}'})]),
    ]

    async def _collect():
        out = []
        async for item in iter_stream_json(redis, "resp:1"):
            out.append(item)
        return out

    out = asyncio.run(_collect())
    assert out == [{"delta": "a"}, {"done": True}]
