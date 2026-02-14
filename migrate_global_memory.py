import asyncio
from sqlalchemy import text
from src.database import engine


async def create_table():
    async with engine.begin() as conn:
        print("Creating ai_global_memory table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_global_memory (
                id SERIAL PRIMARY KEY,
                instruction TEXT NOT NULL,
                source VARCHAR DEFAULT 'user_review',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_global_memory_is_active ON ai_global_memory (is_active);"))
        print("Done.")


if __name__ == "__main__":
    asyncio.run(create_table())
