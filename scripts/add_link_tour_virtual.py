
import asyncio
import os
import sys
from urllib.parse import urlparse
import asyncpg

async def add_link_tour_virtual():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("❌ DATABASE_URL não definido.")
        return

    print(f"🔄 Conectando ao banco para adicionar 'link_tour_virtual'...")
    
    # Parser robusto para DSN (lida com @ no password)
    parsed = urlparse(dsn)
    user = parsed.username
    password = parsed.password
    host = parsed.hostname
    port = parsed.port or 5432
    database = parsed.path.lstrip('/')

    try:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database
        )
        
        # Verifica se a coluna já existe
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'unidades' AND column_name = 'link_tour_virtual'
            )
        """)
        
        if not exists:
            await conn.execute("ALTER TABLE unidades ADD COLUMN link_tour_virtual TEXT")
            print("✅ Coluna 'link_tour_virtual' adicionada com sucesso!")
        else:
            print("ℹ️ Coluna 'link_tour_virtual' já existe.")
            
        await conn.close()
    except Exception as e:
        print(f"❌ Erro na migração: {e}")

if __name__ == "__main__":
    asyncio.run(add_link_tour_virtual())
