import os
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from sqlalchemy import select, func
from src.database import init_db, Account, Transaction, AsyncSessionLocal, Category
from src.parser import BankParser
from src.ai import CategorizerAI
from src.local_llm import LocalLLMPipeline

from src.commands import list_accounts, get_queue_stats, add_transaction, get_queue_transactions, mark_transaction_verified, update_transaction_category, get_category_display_from_values


# States
INPUT_DETAILS, SELECT_ACCOUNT, SELECT_CATEGORY_NUMBER, CONFIRM_NEW_CATEGORY = range(4)
# Review States (managed via callback data mostly, but could use states if we want conversation)



# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ['📊 Stats', '📝 Review'],
        ['➕ Add', '❓ Help']
    ]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 *Welcome to Bluecoins Manager!*\n\n"
        "I can help you manage your finances directly from Telegram.\n"
        "Use the menu button below or types `/help` to see all commands.",
        parse_mode="Markdown",
        reply_markup=markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Bluecoins Manager Help*\n\n"
        "*Core Commands:*\n"
        "📊 `/stats` \- Show review queue summary\n"
        "📝 `/review` \- Process pending transactions\n"
        "➕ `/add <amt> <desc>` \- Quick manual entry\n"
        "📁 `/accounts` \- List & manage accounts\n"
        "🏷️ `/categories` \- View your budget categories\n\n"
        "*Advanced:*\n"
        "🔄 `/reindex` \- Update AI memory from database\n"
        "📄 *Send a CSV/PDF* \- Import bank statements\n\n"
        "*Chatting:*\n"
        "You can ask me questions in natural language, like:\n"
        "_\"How much did I spend on food this month?\"_\n"
        "_\"Why was my last transaction categorized as Utilities?\"_"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def accounts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    async with AsyncSessionLocal() as session:
        if not args:
            # List behavior
            accounts = await list_accounts(session)
            if not accounts:
                await update.message.reply_text("No accounts found.")
                return
            msg = "📁 *Your Accounts:*\n"
            for acc in accounts:
                msg += f"• `{acc.name}` \({acc.institution}\)\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        subcommand = args[0].lower()
        if subcommand == "list":
             accounts = await list_accounts(session)
             if not accounts:
                await update.message.reply_text("No accounts found.")
                return
             msg = "*Accounts:*\n"
             for acc in accounts:
                msg += f"- `{acc.name}` ({acc.institution})\n"
             await update.message.reply_text(msg, parse_mode="Markdown")
        
        elif subcommand == "add":
            if len(args) < 3:
                 await update.message.reply_text("Usage: `/accounts add <name> <institution>`", parse_mode="Markdown")
                 return
            name = args[1]
            institution = args[2]
            
            # Simple add check from bot
            try:
                session.add(Account(name=name, institution=institution))
                await session.commit()
                await update.message.reply_text(f"✅ Account `{name}` added.", parse_mode="Markdown")
            except Exception as e:
                await session.rollback()
                await update.message.reply_text(f"❌ Error: {e}")
        else:
             await update.message.reply_text("Unknown subcommand. Use `list` or `add`.")


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    async with AsyncSessionLocal() as session:
        subcommand = args[0].lower() if args else "list"
        
        if subcommand == "list":
            # Hierarchical view similar to CLI
            result = await session.execute(select(Category).order_by(Category.parent_name, Category.name))
            categories = result.scalars().all()
            if not categories:
                 await update.message.reply_text("No categories found.")
                 return
            
            # Group by Parent
            tree = {}
            for c in categories:
                parent = c.parent_name or "Uncategorized"
                if parent not in tree:
                    tree[parent] = []
                tree[parent].append(c)
            
            msg = "🏷️ *Your Categories:*\n\n"
            for parent, kids in sorted(tree.items()):
                msg += f"📁 *{parent}*\n"
                for kid in kids:
                    msg += f"  └─ `{kid.name}` _({kid.type})_\n"
            
            # Telegram has message length limits; might need splitting if too long
            if len(msg) > 4000:
                msg = msg[:4000] + "\n...(truncated)"
                
            await update.message.reply_text(msg, parse_mode="Markdown")
            
        elif subcommand == "add":
             # Usage: /categories add <name> <type> [parent]
             if len(args) < 3:
                  await update.message.reply_text("Usage: `/categories add <name> <expense|income> [parent]`", parse_mode="Markdown")
                  return
             name = args[1]
             ctype = args[2].lower()
             parent = args[3] if len(args) > 3 else None
             
             if ctype not in ["expense", "income"]:
                  await update.message.reply_text("Type must be 'expense' or 'income'.")
                  return

             # Check existence
             stmt = select(Category).where(
                 Category.name == name,
                 Category.parent_name == parent,
                 Category.type == ctype
             )
             existing = await session.execute(stmt)
             if existing.scalar_one_or_none():
                 await update.message.reply_text("Category already exists.")
                 return
             
             session.add(Category(name=name, parent_name=parent, type=ctype))
             await session.commit()
             label = f"{parent} > {name}" if parent else name
             await update.message.reply_text(f"✅ Category `{label}` added.", parse_mode="Markdown")
        else:
             await update.message.reply_text("Unknown subcommand. Use `list` or `add`.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        rows = await get_queue_stats(session)
        if not rows:
            await update.message.reply_text("Queue is empty/No stats.")
            return
            
        msg = "📊 *Review Queue Summary*\n\n"
        msg += f"`{'State':<12} {'Bucket':<10} {'Qty'}`\n"
        msg += "`" + "─" * 28 + "`\n"
        for state, bucket, count in rows:
             s = (state or "none").capitalize()
             b = (bucket or "none").capitalize()
             msg += f"`{s:<12} {b:<10} {count}`\n"
        
        await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 *Manual Entry Step 1/3*\n\n"
        "Please enter the amount and a brief description\.\n"
        "Format: `Amount Description`\n\n"
        "Example: `50.00 Dinner at Sushi Bar`",
        parse_mode="MarkdownV2"
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
        await update.message.reply_text(
            f"💰 *Manual Entry Step 2/3*\n\n"
            f"*Transaction:* `{amount:.2f}`\n"
            f"*Description:* `{desc}`\n\n"
            "🏦 _Select Account:_ ",
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
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
    context.user_data["add_account"] = account_name
    
    await query.edit_message_text(f"Account: {account_name}\nAnalyzing category for '{desc}'...")
    
    # Run AI Categorization
    async with AsyncSessionLocal() as session:
        ai = CategorizerAI()
        # Get candidates
        candidates = await ai.suggest_category_candidates(
            desc, 
            session, 
            min_candidates=5
        )
        context.user_data["candidates"] = candidates
        
        msg = f"Select Category for *{desc}* (${amount}):\n\n"
        
        # Build numbered list
        for idx, cand in enumerate(candidates, 1):
            cid = cand.get('id')
            reason = cand.get('reasoning', '')
            ctype = cand.get('type', 'expense')
            
            # Fetch names
            if cid:
                 r = await session.execute(select(Category).where(Category.id == cid))
                 c = r.scalar_one_or_none()
                 if c:
                     label = f"{c.parent_name or ''} > {c.name}"
                 else:
                     label = f"ID:{cid}"
            else:
                 label = "Uncategorized"
            
            msg += f"*{idx}.* {label} `({ctype})`\n_{reason}_\n\n"
            
        msg += "Reply with the *number* (e.g., '1') to select."
        
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")
        return SELECT_CATEGORY_NUMBER

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches one pending transaction and shows it."""
    async with AsyncSessionLocal() as session:
        # Get one high priority item
        queue = await get_queue_transactions(session, limit=1)
        if not queue:
            await update.message.reply_text("✅ Review Queue is empty!")
            return
        
        tx = queue[0]
        
        # Format Message
        cat_str = "Uncategorized"
        if tx.category:
            cat_str = f"{tx.category.parent_name} > {tx.category.name}"
        elif tx.type == "transfer":
            cat_str = "Transfer"
            
        msg = (
            f"🔎 *Review Transaction*\n"
            f"📅 {tx.date.strftime('%Y-%m-%d')}\n"
            f"🏦 {tx.account.name if tx.account else 'Unknown'}\n"
            f"📝 *{tx.description}*\n"
            f"💰 *{tx.amount:.2f}*\n"
            f"🏷️ {cat_str} `({tx.type})`\n"
            f"🤖 Conf: {tx.confidence_score:.2f} | Rsn: {tx.decision_reason or 'None'}"
        )
        
        # Buttons
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"rev_ok_{tx.id}"),
                InlineKeyboardButton("⏭️ Skip", callback_data=f"rev_skip_{tx.id}"),
            ],
            [
                InlineKeyboardButton("✏️ Edit Category", callback_data=f"rev_cat_{tx.id}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"rev_del_{tx.id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    parts = data.split("_")
    action = parts[1] # ok, skip, cat, del
    tx_id = int(parts[2])
    
    async with AsyncSessionLocal() as session:
        if action == "ok":
            success, msg = await mark_transaction_verified(session, tx_id)
            if success:
                 await query.edit_message_text(f"✅ Verified transaction.")
                 # Trigger next review? 
                 # await review_command(update, context) # Recursive might be tricky with update obj
            else:
                 await query.edit_message_text(f"❌ Error: {msg}")

        elif action == "skip":
             await query.edit_message_text(f"⏭️ Skipped.")
        
        elif action == "del":
             # Implementation needed depending on policy (soft/hard delete)
             # For now just verify removed
             from src.commands import delete_transaction
             await delete_transaction(session, tx_id)
             await query.edit_message_text(f"🗑️ Deleted.")

        elif action == "cat":
             # This requires user input. We can't easily jump into conversation handler from callback 
             # without returning a state. 
             # Simplified: Ask user to reply with category ID or name? 
             # Better: Show top 5 categories as buttons
             
             # Fetch tx to get desc
             tx = await session.get(Transaction, tx_id)
             if not tx:
                 await query.edit_message_text("Transaction not found.")
                 return

             ai = CategorizerAI()
             candidates = await ai.suggest_category_candidates(tx.description, session, min_candidates=5)
             
             keyboard = []
             for c in candidates:
                 cid = c['id']
                 # Retrieve name
                 r = await session.execute(select(Category).where(Category.id == cid))
                 cat = r.scalar_one_or_none()
                 label = f"{cat.name}" if cat else f"ID {cid}"
                 keyboard.append([InlineKeyboardButton(label, callback_data=f"setcat_{tx_id}_{cid}")])
             
             keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data=f"rev_cancel")])
             reply_markup = InlineKeyboardMarkup(keyboard)
             await query.edit_message_text(
                 f"🏷️ *Select Category* for:\n"
                 f"_{tx.description}_", 
                 parse_mode="Markdown",
                 reply_markup=reply_markup
             )

async def set_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # format: setcat_TXID_CATID
    parts = data.split("_")
    tx_id = int(parts[1])
    cat_id = int(parts[2])
    
    async with AsyncSessionLocal() as session:
        success, msg = await update_transaction_category(session, tx_id, cat_id)
        if success:
             await query.edit_message_text(f"✅ Category updated.")
        else:
             await query.edit_message_text(f"❌ Error: {msg}")

async def select_category_number(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()
    candidates = context.user_data.get("candidates", [])
    
    try:
        selection = int(text)
        if 1 <= selection <= len(candidates):
            choice = candidates[selection - 1]
            cat_id = choice.get('id')
            tx_type = choice.get('type', 'expense')
            
            # Finalize Transaction
            amount = context.user_data.get("add_amount")
            desc = context.user_data.get("add_desc")
            acc_name = context.user_data.get("add_account")
            
            async with AsyncSessionLocal() as session:
                success, msg, tx = await add_transaction(
                    session, 
                    datetime.now(), 
                    amount, 
                    desc, 
                    acc_name, 
                    category_id=cat_id, 
                    type=tx_type
                )
                
                # Fetch category name for better confirmation
                cat_name = "Unknown"
                if cat_id:
                    res = await session.execute(select(Category).where(Category.id == cat_id))
                    cat = res.scalar_one_or_none()
                    cat_name = cat.name if cat else "Unknown"

                await update.message.reply_text(
                    f"✅ *Transaction Saved\!*\n\n"
                    f"💰 *Amount:* `{amount:.2f}`\n"
                    f"🏦 *Account:* `{acc_name}`\n"
                    f"🏷️ *Category:* `{cat_name}`",
                    parse_mode="MarkdownV2"
                )
            return ConversationHandler.END
        else:
             await update.message.reply_text(f"Please enter a number between 1 and {len(candidates)}.")
             return SELECT_CATEGORY_NUMBER
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return SELECT_CATEGORY_NUMBER

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ *Operation cancelled\.*", parse_mode="MarkdownV2")
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
            
            # Trigger background reindex (or just do it here if small)
            if new_count > 0:
                llm = LocalLLMPipeline()
                res = await llm.reindex_transactions(session, since=None) 
                # Optimization: pass 'since' if we tracked last sync time, but for now reindex all is safer
                await update.message.reply_text(f"🧠 Knowledge updated: {res['created']} new chunks.")



    except Exception as e:
        logging.error(f"Error processing file: {e}")
        await update.message.reply_text(f"❌ Error occurred: {str(e)}")

async def reindex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Re-indexing transaction knowledge base...")
    async with AsyncSessionLocal() as session:
        llm = LocalLLMPipeline()
        try:
            res = await llm.reindex_transactions(session)
            await update.message.reply_text(
                f"✅ Index Complete.\n"
                f"Created: {res['created']}\n"
                f"Updated: {res['updated']}\n"
                f"Total: {res['total']}"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle natural language questions via RAG.
    """
    user_text = update.message.text
    if not user_text:
        return

    # Ignore if in conversation state (handled by conv_handler)
    # But this handler is added last, so it catches anything not trapped by conv_handler or commands.
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    async with AsyncSessionLocal() as session:
        llm = LocalLLMPipeline()
        try:
             # RAG Answer
             result = await llm.answer(session, user_text, top_k=5)
             answer = result["answer"]
             
             # Extract sources for citation
             sources = []
             for ctx in result.get("contexts", [])[:3]:
                 # Format: "Date: Desc (Amount)"
                 # We have content string, let's just parse or use metadata if available
                 # metadata is not in the dict returned by answer() currently, logic in local_llm.py 
                 # answer() returns dict with 'contexts' list of dicts.
                 # Let's trust the answer for now, or append top source.
                 content_preview = ctx['content'].split('\n')[2] # Description line usually
                 sources.append(f"- {content_preview}")
             
             reply = f"{answer}"
             if sources:
                 reply += "\n\n*Sources:*\n" + "\n".join(sources)
                 
             # Split if too long
             if len(reply) > 4000:
                reply = reply[:4000] + "..."
                
             await update.message.reply_text(reply, parse_mode="Markdown")
             
        except Exception as e:
             logging.error(f"LLM Error: {e}")
             await update.message.reply_text("🤖 I'm having trouble thinking right now. Is Ollama running?")



async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 Stats':
        return await stats_command(update, context)
    elif text == '📝 Review':
        return await review_command(update, context)
    elif text == '➕ Add':
        # Start the add conversation
        return await start_add(update, context)
    elif text == '❓ Help':
        return await help_command(update, context)
    else:
        # Pass to general chat handle
        return await handle_chat_message(update, context)

async def post_init(application):
    commands = [
        BotCommand("stats", "Quick summary of review queue"),
        BotCommand("review", "Start reviewing transactions"),
        BotCommand("add", "Add a manual transaction"),
        BotCommand("accounts", "List all accounts"),
        BotCommand("categories", "View budget categories"),
        BotCommand("help", "Show detailed guide")
    ]
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env file.")
        print("Please create .env with TELEGRAM_BOT_TOKEN=your_token_here")
        exit(1)
        
    print("Bot is starting...")
    app = ApplicationBuilder().token(token).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("accounts", accounts_command))
    app.add_handler(CommandHandler("categories", categories_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("reindex", reindex_command))
    
    # Review Callbacks
    app.add_handler(CallbackQueryHandler(review_callback, pattern="^rev_"))
    app.add_handler(CallbackQueryHandler(set_category_callback, pattern="^setcat_"))
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add", start_add),
            MessageHandler(filters.Regex('^➕ Add$'), start_add)
        ],
        states={
            INPUT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_details)],
            SELECT_ACCOUNT: [CallbackQueryHandler(select_account_callback)],
            SELECT_CATEGORY_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_category_number)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Handle Keyboard Buttons
    app.add_handler(MessageHandler(filters.Regex('^(📊 Stats|📝 Review|➕ Add|❓ Help)$'), handle_keyboard_button))
    
    # Fallback to Chat (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))
    
    app.run_polling()
