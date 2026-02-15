import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from sqlalchemy import select, func
from src.database import init_db, Account, Transaction, AsyncSessionLocal
from src.parser import BankParser
from src.ai import CategorizerAI

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I am your Bluecoins Manager Bot.\n"
        "Send me a bank CSV file (e.g., 'HSBC_Statement.csv') to process transactions.\n"
        "Make sure the filename contains the bank name (HSBC, Wise)."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    file = await document.get_file()
    
    # Check extension
    if not document.file_name.lower().endswith('.csv'):
        await update.message.reply_text("Please send a CSV file.")
        return

    # Ensure uploads dir exists
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{document.file_name}"
    await file.download_to_drive(file_path)
    
    await update.message.reply_text(f"Received {document.file_name}. Processing...")
    
    try:
        # Determine Bank
        parser = BankParser()
        filename_upper = document.file_name.upper()
        bank_name = None
        
        # Simple heuristic mapping
        # Ideally query DB for supported banks?
        # But parser has config.
        if "HSBC" in filename_upper:
            bank_name = "HSBC"
        elif "WISE" in filename_upper:
            bank_name = "Wise"
        else:
            await update.message.reply_text("Could not detect bank from filename. Please rename file to include 'HSBC' or 'Wise'.")
            return

        # Parse Transactions
        transactions = parser.parse(bank_name, file_path)
        
        async with AsyncSessionLocal() as session:
            # Find Account
            stmt = select(Account).where(Account.institution == bank_name)
            res = await session.execute(stmt)
            accounts = res.scalars().all()
            
            if not accounts:
                await update.message.reply_text(f"No account found for bank '{bank_name}'. Please add it via CLI (`python main.py account --add ...`).")
                return
            
            # Use first account found (User could have multiple HSBC accounts, handling that is complex for Phase 1)
            account = accounts[0]
            
            # AI Instance
            ai = CategorizerAI()
            
            new_count = 0
            for tx in transactions:
                # Duplicate Check: Date, Amount, Description, Account
                stmt = select(Transaction).where(
                    Transaction.date == tx["date"],
                    Transaction.amount == tx["amount"],
                    Transaction.description == tx["description"], # Exact match description
                    Transaction.account_id == account.id
                )
                existing = await session.execute(stmt)
                if existing.scalar_one_or_none():
                    continue
                
                # Categorize
                cat_id, confidence, reasoning, suggested_type = await ai.suggest_category(
                    tx["description"],
                    session,
                    expected_type=tx["type"] if tx["type"] in {"expense", "income"} else None,
                )
                tx_type = suggested_type or tx["type"]
                if tx_type == "transfer":
                    cat_id = None
                
                new_tx = Transaction(
                    date=tx["date"],
                    description=tx["description"],
                    amount=tx["amount"],
                    type=tx_type,
                    account_id=account.id,
                    category_id=cat_id,
                    raw_csv_row=tx["raw_csv_row"]
                )
                session.add(new_tx)
                new_count += 1
            
            await session.commit()
            
            msg = f"✅ Processing Complete!\n"
            msg += f"Bank: {bank_name}\n"
            msg += f"Account: {account.name}\n"
            msg += f"New Transactions: {new_count}\n"
            
            await update.message.reply_text(msg)

    except Exception as e:
        logging.error(f"Error processing file: {e}")
        await update.message.reply_text(f"❌ Error occurred: {str(e)}")

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env file.")
        print("Please create .env with TELEGRAM_BOT_TOKEN=your_token_here")
        exit(1)
        
    print("Bot is starting...")
    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    app.run_polling()
