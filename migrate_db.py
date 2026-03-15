import asyncio
import src.core.database as _db

async def run():
    print("START MIGRATION")
    await _db.init_db_pool()
    if not _db.db_pool:
        print("FAIL POOL")
        return
    try:
        # 1. Update mensagens
        print("Updating 'mensagens'...")
        await _db.db_pool.execute("ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS empresa_id INTEGER REFERENCES empresas(id)")
        await _db.db_pool.execute("""
            UPDATE mensagens m 
            SET empresa_id = c.empresa_id 
            FROM conversas c 
            WHERE m.conversa_id = c.id AND m.empresa_id IS NULL
        """)
        
        # 2. Update eventos_funil
        print("Updating 'eventos_funil'...")
        await _db.db_pool.execute("ALTER TABLE eventos_funil ADD COLUMN IF NOT EXISTS empresa_id INTEGER REFERENCES empresas(id)")
        await _db.db_pool.execute("""
            UPDATE eventos_funil ef 
            SET empresa_id = c.empresa_id 
            FROM conversas c 
            WHERE ef.conversa_id = c.id AND ef.empresa_id IS NULL
        """)

        print("MIGRATION FINISHED")
        await _db.close_db_pool()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run())
