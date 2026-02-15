import os
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from src.database import init_db, Account, Transaction, AsyncSessionLocal
from src.parser import BankParser
from src.ai import CategorizerAI
from src.commands import list_accounts, get_queue_stats, add_transaction

# States
INPUT_DETAILS, SELECT_ACCOUNT = range(2)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I am your Bluecoins Manager Bot.\n"
        "Commands:\n"
        "/accounts - List accounts\n"
        "/stats - Show review queue stats\n"
        "/add - Add a manual transaction\n"
        "Or send a CSV file to import."
    )

async def accounts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        accounts = await list_accounts(session)
        if not accounts:
            await update.message.reply_text("No accounts found.")
            return
            
        msg = "Accounts:\n"
        for acc in accounts:
            msg += f"- {acc.name} ({acc.institution})\n"
        await update.message.reply_text(msg)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        rows = await get_queue_stats(session)
        if not rows:
            await update.message.reply_text("Queue is empty/No stats.")
            return
            
        msg = "Review Queue Stats:\n"
        msg += f"{'State':<15} {'Bucket':<10} {'Count'}\n"
        msg += "-" * 35 + "\n"
        for state, bucket, count in rows:
             msg += f"{state or 'none':<15} {bucket or 'none':<10} {count}\n"
        await update.message.reply_text(f"```\n{msg}\n```", parse_mode="MarkdownV2")

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please enter the transaction details in format:\n"
        "`Amount Description`\n"
        "Example: `50.00 Lunch at Cafe`",
        parse_mode="Markdown"
    )
    return INPUT_DETAILS

async def receive_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parts = text.split(" ", 1)
    if len(parts) < 2:
         await update.message.reply_text("Invalid format. Please use: `Amount Description`")
         return INPUT_DETAILS
    
    amount_str, desc = parts
    try:
        amount = float(amount_str)
    except ValueError:
        await update.message.reply_text("Invalid amount. Please use a number.")
        return INPUT_DETAILS
        
    context.user_data["add_amount"] = amount
    context.user_data["add_desc"] = desc
    
    # Get Accounts
    async with AsyncSessionLocal() as session:
        accounts = await list_accounts(session)
        if not accounts:
            await update.message.reply_text("No accounts found. Add one via CLI first.")
            return ConversationHandler.END
            
        keyboard = []
        for acc in accounts:
            keyboard.append([InlineKeyboardButton(acc.name, callback_data=f"acc_{acc.name}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Transaction: {amount} for '{desc}'.\nSelect Account:", reply_markup=reply_markup)
        return SELECT_ACCOUNT

async def select_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith("acc_"):
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
        
    account_name = data[4:] # remove acc_
    amount = context.user_data.get("add_amount")
    desc = context.user_data.get("add_desc")
    
    async with AsyncSessionLocal() as session:
        success, msg, tx = await add_transaction(session, datetime.now(), amount, desc, account_name)
        await query.edit_message_text(f"✅ {msg}")
        
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

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
    app.add_handler(CommandHandler("accounts", accounts_command))
    app.add_handler(CommandHandler("stats", stats_command))
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", start_add)],
        states={
            INPUT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_details)],
            SELECT_ACCOUNT: [CallbackQueryHandler(select_account_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    app.run_polling()
