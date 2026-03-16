import asyncio
import redis.asyncio as redis
from src.core.config import REDIS_URL, logger

async def unpause_all():
    if not REDIS_URL:
        print("❌ REDIS_URL não definida.")
        return

    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        keys = await r.keys("pause_ia:*")
        if not keys:
            print("✅ Nenhuma conversa pausada encontrada.")
            return

        print(f"🔄 Encontradas {len(keys)} conversas pausadas. Desbloqueando...")
        for key in keys:
            await r.delete(key)
            print(f"🔓 {key} desbloqueada.")
        
        print(f"✨ Todas as {len(keys)} conversas foram desbloqueadas com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao acessar Redis: {e}")
    finally:
        await r.aclose()

if __name__ == "__main__":
    asyncio.run(unpause_all())
