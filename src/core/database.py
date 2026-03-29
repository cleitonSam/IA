import asyncpg
import urllib.parse
from typing import Optional
from src.core.config import DATABASE_URL, logger

db_pool: Optional[asyncpg.Pool] = None

async def init_db_pool():
    global db_pool
    if DATABASE_URL:
        try:
            # Tratamento robusto para senhas com caracteres especiais (@, #, etc)
            dsn = DATABASE_URL
            if "://" in dsn and "@" in dsn:
                try:
                    prefix, rest = dsn.split("://", 1)
                    prefix = "postgresql" # asyncpg e sqlalchemy preferem postgresql
                    # Divide pelo ÚLTIMO '@' para separar credenciais de host
                    credentials, host_info = rest.rsplit("@", 1)
                    if ":" in credentials:
                        user, password = credentials.split(":", 1)
                        # UNQUOTE primeiro caso já venha escapado, depois QUOTE_PLUS para garantir
                        raw_password = urllib.parse.unquote(password)
                        encoded_password = urllib.parse.quote_plus(raw_password)
                        dsn = f"{prefix}://{user}:{encoded_password}@{host_info}"
                except Exception:
                    pass # Fallback para original se falhar o parsing

            db_pool = await asyncpg.create_pool(
                dsn,
                min_size=2,
                max_size=10,
                command_timeout=10,
                timeout=5,       # timeout para adquirir conexão do pool
            )
            logger.info("✅ Conectado ao PostgreSQL com sucesso!")
        except Exception as e:
            # Mascarar senha para o log (por segurança)
            safe_dsn = dsn.split("@")[-1] if "@" in dsn else dsn
            logger.error(f"❌ Falha crítica ao conectar no PostgreSQL ({safe_dsn}): {type(e).__name__}: {e}")
    else:
        logger.warning("⚠️ DATABASE_URL não definido - modo sem banco de dados (limitado)")

async def close_db_pool():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("❌ Conexão PostgreSQL encerrada.")
