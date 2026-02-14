
import asyncio
from sqlalchemy import text
from src.database import engine

async def create_table():
    async with engine.begin() as conn:
        print("Creating ai_memory table...")
        # PostgreSQL syntax
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_memory (
                id SERIAL PRIMARY KEY,
                transaction_id INTEGER REFERENCES transactions(id),
                pattern_key VARCHAR,
                ai_suggested_category_id INTEGER,
                user_selected_category_id INTEGER,
                ai_reasoning TEXT,
                reflection TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("Creating index on pattern_key...")
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_memory_pattern_key ON ai_memory (pattern_key);"))
        print("Done.")

if __name__ == "__main__":
    asyncio.run(create_table())
