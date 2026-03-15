import asyncio
import src.core.database as _db

async def run():
    await _db.init_db_pool()
    try:
        col = await _db.db_pool.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'personalidade_ia'")
        print("--- PERSONALIDADE_IA COLUMNS ---")
        for c in col:
            print(c['column_name'])
        await _db.close_db_pool()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run())
