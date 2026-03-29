"""
Fixtures globais para testes do Antigravity IA.

Fornece mocks de Redis, DB pool e LLM para testes unitários sem dependências externas.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ─── Fake Redis ───────────────────────────────────────────────
class FakeRedis:
    """In-memory Redis mock supporting get/set/exists/rpush/expire/pipeline/xadd/xreadgroup."""

    def __init__(self):
        self._store = {}
        self._lists = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def setex(self, key, ttl, value):
        self._store[key] = value
        return True

    async def exists(self, key):
        return key in self._store or key in self._lists

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)
            self._lists.pop(k, None)

    async def incr(self, key):
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    async def expire(self, key, ttl):
        return True

    async def rpush(self, key, *values):
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].extend(values)
        return len(self._lists[key])

    async def lrange(self, key, start, stop):
        return self._lists.get(key, [])[start:stop + 1 if stop != -1 else None]

    async def llen(self, key):
        return len(self._lists.get(key, []))

    async def xadd(self, stream, fields):
        if stream not in self._lists:
            self._lists[stream] = []
        msg_id = f"{len(self._lists[stream])}-0"
        self._lists[stream].append((msg_id, fields))
        return msg_id

    async def xack(self, stream, group, msg_id):
        return 1

    async def xdel(self, stream, msg_id):
        return 1

    async def xlen(self, stream):
        return len(self._lists.get(stream, []))

    async def xreadgroup(self, group, consumer, streams, count=1, block=0):
        results = []
        for stream_key, last_id in streams.items():
            msgs = self._lists.get(stream_key, [])
            if msgs:
                results.append((stream_key, msgs[:count]))
                self._lists[stream_key] = msgs[count:]
        return results if results else None

    async def xgroup_create(self, stream, group, id="0", mkstream=False):
        return True

    async def eval(self, script, numkeys, *args):
        return 1

    def pipeline(self, transaction=False):
        return FakePipeline(self)


class FakePipeline:
    """Minimal pipeline that collects commands and executes them."""

    def __init__(self, redis):
        self._redis = redis
        self._commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def rpush(self, key, *values):
        self._commands.append(("rpush", key, values))

    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))

    def incr(self, key):
        self._commands.append(("incr", key))

    def lrange(self, key, start, stop):
        self._commands.append(("lrange", key, start, stop))

    def delete(self, key):
        self._commands.append(("delete", key))

    async def execute(self):
        results = []
        for cmd in self._commands:
            op = cmd[0]
            if op == "rpush":
                r = await self._redis.rpush(cmd[1], *cmd[2])
                results.append(r)
            elif op == "expire":
                results.append(True)
            elif op == "incr":
                r = await self._redis.incr(cmd[1])
                results.append(r)
            elif op == "lrange":
                r = await self._redis.lrange(cmd[1], cmd[2], cmd[3])
                results.append(r)
            elif op == "delete":
                await self._redis.delete(cmd[1])
                results.append(1)
        self._commands.clear()
        return results


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def mock_redis(fake_redis):
    """Patches src.core.redis_client.redis_client with FakeRedis."""
    with patch("src.core.redis_client.redis_client", fake_redis):
        yield fake_redis


# ─── Fake DB Pool ─────────────────────────────────────────────
class FakeDBPool:
    """Minimal asyncpg pool mock."""

    def __init__(self):
        self._data = {}

    async def fetchval(self, query, *args):
        return self._data.get(("fetchval", query), None)

    async def fetchrow(self, query, *args):
        return self._data.get(("fetchrow", query), None)

    async def fetch(self, query, *args):
        return self._data.get(("fetch", query), [])

    async def execute(self, query, *args):
        return "OK"


@pytest.fixture
def fake_db():
    return FakeDBPool()


@pytest.fixture
def mock_db(fake_db):
    """Patches src.core.database.db_pool with FakeDBPool."""
    with patch("src.core.database.db_pool", fake_db):
        yield fake_db


# ─── Mock LLM ─────────────────────────────────────────────────
@pytest.fixture
def mock_llm():
    """Returns a mock that can be used to mock LLM responses."""
    mock = AsyncMock()
    choice = MagicMock()
    choice.message.content = "Resposta padrão do LLM"
    mock.chat.completions.create.return_value = MagicMock(choices=[choice])
    return mock
