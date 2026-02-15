import asyncio
from sqlalchemy import text
from src.database import engine


async def migrate():
    async with engine.begin() as conn:
        print("Adding review-queue columns...")
        await conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS decision_state VARCHAR;"))
        await conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS decision_reason TEXT;"))
        await conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS review_priority INTEGER;"))
        await conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS review_bucket VARCHAR;"))

        await conn.execute(text("ALTER TABLE ai_memory ADD COLUMN IF NOT EXISTS policy_version VARCHAR;"))
        await conn.execute(text("ALTER TABLE ai_memory ADD COLUMN IF NOT EXISTS threshold_used FLOAT;"))
        await conn.execute(text("ALTER TABLE ai_memory ADD COLUMN IF NOT EXISTS conflict_flags_json TEXT;"))

        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transactions_decision_state ON transactions (decision_state);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transactions_review_priority ON transactions (review_priority);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transactions_review_bucket ON transactions (review_bucket);"))

        await conn.execute(text("""
            UPDATE transactions
            SET decision_state = COALESCE(decision_state, 'needs_review'),
                review_priority = COALESCE(review_priority, 50),
                review_bucket = COALESCE(review_bucket, 'legacy'),
                decision_reason = COALESCE(decision_reason, 'Backfilled by migrate_review_queue.py')
            WHERE decision_state IS NULL
               OR review_priority IS NULL
               OR review_bucket IS NULL
               OR decision_reason IS NULL;
        """))

        print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
