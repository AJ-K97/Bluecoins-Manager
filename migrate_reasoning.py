
import asyncio
from sqlalchemy import text
from src.database import engine

async def add_column():
    async with engine.begin() as conn:
        print("Adding ai_reasoning column...")
        try:
            await conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS ai_reasoning TEXT;"))
            print("Done.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(add_column())
