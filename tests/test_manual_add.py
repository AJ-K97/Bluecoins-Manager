import asyncio
import os
import sys
from datetime import datetime

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import engine, Base, AsyncSessionLocal, Account, Transaction
from src.commands import add_account, add_transaction

async def test_manual_add():
    # Setup Test DB (InMemory or file)
    # For simplicity, we use the main logic but maybe different DB URL? 
    # The code uses 'src.database.engine' which is hardcoded to 'bluecoins.db' usually.
    # We will just run it against the real DB or a test one if configured.
    # Given the environment, let's just make sure "TestAccount" exists in the real DB 
    # and add a test transaction, then delete it.
    
    async with AsyncSessionLocal() as session:
        print("Ensuring TestAccount exists...")
        await add_account(session, "TestAccount", "TestBank")
        
        print("Adding manual transaction...")
        success, msg, tx = await add_transaction(
            session, 
            date="2025-01-01", 
            amount=123.45, 
            description="Test Manual Entry via Script", 
            account_name="TestAccount"
        )
        
        print(f"Result: {success} - {msg}")
        
        if not success:
            print("FAILED: Could not add transaction.")
            return

        # Verify
        print(f"Verifying Transaction ID: {tx.id}")
        assert tx.id is not None
        assert tx.amount == 123.45
        assert tx.description == "Test Manual Entry via Script"
        
        # Cleanup
        print("Cleaning up...")
        await session.delete(tx)
        
        # Remove account if we want, but might be useful to keep for CLI test.
        # Let's keep account.
        
        await session.commit()
        print("PASSED: test_manual_add")

if __name__ == "__main__":
    asyncio.run(test_manual_add())
