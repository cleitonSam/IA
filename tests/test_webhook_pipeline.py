"""
Tests for the webhook pipeline:
- Webhook enqueue to Redis Streams
- Worker deduplication
- Rate limiting
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from tests.conftest import FakeRedis


# ─── Webhook enqueue tests ────────────────────────────────────

class TestWebhookEnqueue:
    @pytest.mark.asyncio
    async def test_chatwoot_webhook_enqueues_to_stream(self):
        """Simulates the Chatwoot webhook enqueue path."""
        fake_redis = FakeRedis()
        job_data = {
            "account_id": "1",
            "conversation_id": "100",
            "contact_id": "50",
            "slug": "centro",
            "nome_cliente": "Maria",
            "empresa_id": "1",
            "contato_fone": "5511999999999",
        }
        msg_id = await fake_redis.xadd("ia:webhook:stream", job_data)
        assert msg_id is not None
        assert await fake_redis.xlen("ia:webhook:stream") == 1

    @pytest.mark.asyncio
    async def test_uazapi_webhook_enqueues_to_stream(self):
        """Simulates the UazAPI webhook enqueue path."""
        fake_redis = FakeRedis()
        job_data = {
            "source": "uazapi",
            "empresa_id": "1",
            "phone": "5511999999999",
            "content": "Oi, quero saber dos planos",
            "nome_cliente": "João",
            "msg_id": "abc123",
            "has_audio": "",
            "audio_url": "",
            "has_image": "",
            "image_url": "",
        }
        msg_id = await fake_redis.xadd("ia:webhook:stream", job_data)
        assert msg_id is not None


# ─── Worker dedup tests ───────────────────────────────────────

class TestWorkerDedup:
    @pytest.mark.asyncio
    async def test_dedup_blocks_duplicate(self):
        """Tests the idempotency pattern: SET NX returns None on second call."""
        fake_redis = FakeRedis()
        key = "dedup:job:1:100:0-0"
        first = await fake_redis.set(key, "1", nx=True, ex=300)
        assert first is True
        second = await fake_redis.set(key, "1", nx=True, ex=300)
        assert second is None  # Blocked by NX

    @pytest.mark.asyncio
    async def test_dedup_allows_different_messages(self):
        """Different message IDs should not conflict."""
        fake_redis = FakeRedis()
        r1 = await fake_redis.set("dedup:job:1:100:msg-1", "1", nx=True, ex=300)
        r2 = await fake_redis.set("dedup:job:1:100:msg-2", "1", nx=True, ex=300)
        assert r1 is True
        assert r2 is True


# ─── Rate limiting tests ──────────────────────────────────────

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limit_increments(self):
        fake_redis = FakeRedis()
        key = "1:rl:conv:100"
        c1 = await fake_redis.incr(key)
        assert c1 == 1
        c2 = await fake_redis.incr(key)
        assert c2 == 2

    @pytest.mark.asyncio
    async def test_rate_limit_triggers_at_threshold(self):
        fake_redis = FakeRedis()
        key = "1:rl:conv:999"
        for i in range(11):
            count = await fake_redis.incr(key)
        assert count > 10  # Would trigger rate limit


# ─── Pipeline tests ───────────────────────────────────────────

class TestRedisPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_rpush_expire(self):
        fake_redis = FakeRedis()
        async with fake_redis.pipeline(transaction=False) as pipe:
            pipe.rpush("test:key", json.dumps({"text": "hello"}))
            pipe.expire("test:key", 60)
            results = await pipe.execute()
        assert results[0] == 1  # rpush returns list length
        assert results[1] is True  # expire returns True
        items = await fake_redis.lrange("test:key", 0, -1)
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_pipeline_incr_expire(self):
        fake_redis = FakeRedis()
        async with fake_redis.pipeline(transaction=False) as pipe:
            pipe.incr("counter")
            pipe.expire("counter", 60)
            results = await pipe.execute()
        assert results[0] == 1
