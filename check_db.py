import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def check_db():
    try:
        async with AsyncSessionLocal() as session:
            print("Connected to DB.")
            
            # List tables
            result = await session.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = result.scalars().all()
            print(f"Tables: {tables}")
            
            if not tables:
                print("No tables found. DB is empty.")
                return

            for table in tables:
                count = await session.execute(text(f"SELECT count(*) FROM {table}"))
                print(f"{table}: {count.scalar()} rows")
                
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(check_db())
