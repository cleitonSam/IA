import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def run():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL não encontrado no .env")
        return

    # Tratamento robusto para senhas com caracteres especiais
    dsn = db_url
    if "://" in dsn and "@" in dsn:
        import urllib.parse
        try:
            prefix, rest = dsn.split("://", 1)
            prefix = "postgres" 
            credentials, host_info = rest.rsplit("@", 1)
            if ":" in credentials:
                user, password = credentials.split(":", 1)
                raw_password = urllib.parse.unquote(password)
                encoded_password = urllib.parse.quote_plus(raw_password)
                dsn = f"{prefix}://{user}:{encoded_password}@{host_info}"
        except Exception:
            pass

    try:
        conn = await asyncpg.connect(dsn)
        print("✅ Conectado ao banco.")
        
        # Verifica se a coluna já existe
        exists = await conn.fetchval("""
            SELECT count(*) 
            FROM information_schema.columns 
            WHERE table_name='unidades' AND column_name='foto_grade'
        """)
        
        if exists == 0:
            await conn.execute("ALTER TABLE unidades ADD COLUMN foto_grade TEXT")
            print("🚀 Coluna 'foto_grade' adicionada com sucesso!")
        else:
            print("ℹ️ Coluna 'foto_grade' já existe.")
            
        await conn.close()
    except Exception as e:
        print(f"❌ Erro ao rodar migração: {e}")

if __name__ == "__main__":
    asyncio.run(run())
