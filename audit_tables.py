import asyncio
import src.core.database as _db

async def run():
    await _db.init_db_pool()
    try:
        tables = ['eventos_funil', 'followups', 'personalidade_ia', 'integracoes']
        for table in tables:
            col = await _db.db_pool.fetch(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")
            print(f"--- {table.upper()} COLUMNS ---")
            cols = [c['column_name'] for c in col]
            print(cols)
            if 'empresa_id' not in cols:
                print(f"!!! MISSING empresa_id in {table}")
        await _db.close_db_pool()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run())
