import asyncpg
from typing import Optional
from src.core.config import DATABASE_URL, logger

db_pool: Optional[asyncpg.Pool] = None

async def init_db_pool():
    global db_pool
    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
            logger.info("✅ Conectado ao PostgreSQL com sucesso!")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar ao PostgreSQL: {e}")
    else:
        logger.warning("⚠️ DATABASE_URL não definido - modo sem banco de dados (limitado)")

async def close_db_pool():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("❌ Conexão PostgreSQL encerrada.")
