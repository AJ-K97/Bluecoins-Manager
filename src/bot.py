import os
import logging
import asyncio
import html
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from sqlalchemy import select, func
from src.database import (
    AsyncSessionLocal, Account, Transaction, Category, 
    LLMKnowledgeChunk, LLMFineTuneExample, LLMSkill
)
from src.parser import BankParser
from src.ai import CategorizerAI
from src.local_llm import LocalLLMPipeline
from src.intents import IntentAI

from src.commands import list_accounts, get_queue_stats, add_transaction, get_queue_transactions, mark_transaction_verified, update_transaction_category, get_category_display_from_values


# States
(INPUT_DETAILS, SELECT_ACCOUNT, SELECT_CATEGORY_NUMBER, CONFIRM_NEW_CATEGORY, 
 INPUT_RULEBOOK_TEXT, SELECT_RULEBOOK_TYPE,
 INPUT_ACCOUNT_NAME, INPUT_ACCOUNT_INST,
 INPUT_CATEGORY_NAME, INPUT_CATEGORY_TYPE, INPUT_CATEGORY_PARENT) = range(11)
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

async def rulebook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📚 List Knowledge", callback_data="rb_list_k")],
        [InlineKeyboardButton("🎯 List Examples", callback_data="rb_list_e")],
        [InlineKeyboardButton("➕ Add Entry", callback_data="rb_add_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # Filter out or escape MarkdownV2 special characters
    await update.message.reply_text(
        "📝 *AI Rulebook Management*\n\n"
        "Configure how the AI thinks and categorizes:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def rb_list_knowledge(query, session):
    res = await session.execute(select(LLMKnowledgeChunk).order_by(LLMKnowledgeChunk.created_at.desc()).limit(10))
    chunks = res.scalars().all()
    if not chunks:
        await query.edit_message_text("No knowledge chunks found.")
        return
    
    msg = "📚 *Recently Added Knowledge:*\n\n"
    keyboard = []
    for c in chunks:
        # Truncate content for display
        tiny_content = (c.content[:50] + '...') if len(c.content) > 50 else c.content
        msg += f"• `ID {c.id}`: {tiny_content}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ Delete {c.id}", callback_data=f"rb_del_k_{c.id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="rb_main")])
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def rb_list_examples(query, session):
    res = await session.execute(select(LLMFineTuneExample).order_by(LLMFineTuneExample.created_at.desc()).limit(10))
    examples = res.scalars().all()
    if not examples:
        await query.edit_message_text("No fine-tune examples found.")
        return
    
    msg = "🎯 *Recent Training Examples:*\n\n"
    keyboard = []
    for e in examples:
        msg += f"• `ID {e.id}`: {e.prompt[:30]}... -> {e.response[:20]}...\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ Delete {e.id}", callback_data=f"rb_del_e_{e.id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="rb_main")])
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def rb_delete_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # format: rb_del_[k|e]_ID
    parts = query.data.split("_")
    rb_type = parts[2]
    rb_id = int(parts[3])
    
    async with AsyncSessionLocal() as session:
        if rb_type == "k":
            obj = await session.get(LLMKnowledgeChunk, rb_id)
        else:
            obj = await session.get(LLMFineTuneExample, rb_id)
            
        if obj:
            await session.delete(obj)
            await session.commit()
            await query.edit_message_text(f"✅ Deleted entry `{rb_id}`.", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ Entry `{rb_id}` not found.")
    
    # Return to main after a short delay or just stay here? 
    # Let's show back button
    keyboard = [[InlineKeyboardButton("🔙 Back to Rulebook", callback_data="rb_main")]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def rulebook_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    async with AsyncSessionLocal() as session:
        if data == "rb_list_k":
            await rb_list_knowledge(query, session)
        elif data == "rb_list_e":
            await rb_list_examples(query, session)
        elif data.startswith("rb_del_"):
            await rb_delete_entry(update, context)
        elif data == "rb_main":
             keyboard = [
                [InlineKeyboardButton("📚 List Knowledge", callback_data="rb_list_k")],
                [InlineKeyboardButton("🎯 List Examples", callback_data="rb_list_e")],
                [InlineKeyboardButton("➕ Add Entry", callback_data="rb_add_start")]
            ]
             await query.edit_message_text(
                "📝 *AI Rulebook Management*\n\n"
                "Configure how the AI thinks and categorizes:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    async with AsyncSessionLocal() as session:
        if data == "acc_list":
            accounts = await list_accounts(session)
            if not accounts:
                await query.edit_message_text("No accounts found.")
                return
            msg = "📁 *Your Accounts:*\n\n"
            keyboard = []
            for acc in accounts:
                msg += f"• `{acc.name}` \({acc.institution}\)\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete {acc.name}", callback_data=f"acc_del_{acc.id}")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="acc_main")])
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data.startswith("acc_del_"):
            acc_id = int(data.split("_")[2])
            acc = await session.get(Account, acc_id)
            if acc:
                await session.delete(acc)
                await session.commit()
                await query.edit_message_text(f"✅ Account `{acc.name}` deleted.")
            else:
                await query.edit_message_text("❌ Account not found.")
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="acc_main")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "acc_main":
            keyboard = [
                [InlineKeyboardButton("📁 List Accounts", callback_data="acc_list")],
                [InlineKeyboardButton("➕ Add Account", callback_data="acc_add_start")],
            ]
            await query.edit_message_text("📁 *Account Management*\n\nManage your financial institutions:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    async with AsyncSessionLocal() as session:
        if data == "cat_list":
            result = await session.execute(select(Category).order_by(Category.parent_name, Category.name))
            categories = result.scalars().all()
            if not categories:
                 await query.edit_message_text("No categories found.")
                 return
            
            tree = {}
            for c in categories:
                parent = c.parent_name or "Uncategorized"
                if parent not in tree: tree[parent] = []
                tree[parent].append(c)
            
            msg = "🏷️ *Your Categories:*\n\n"
            keyboard = []
            for parent, kids in sorted(tree.items()):
                msg += f"📁 *{parent}*\n"
                for kid in kids:
                    msg += f"  └─ `{kid.name}` _({kid.type})_\n"
                    keyboard.append([InlineKeyboardButton(f"🗑️ Del {kid.name}", callback_data=f"cat_del_{kid.id}")])
            
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="cat_main")])
            # Limit to top 8 + back to avoid keyboard too large
            await query.edit_message_text(msg[:4000], parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard[:8] + [keyboard[-1]]))
        
        elif data.startswith("cat_del_"):
            cat_id = int(data.split("_")[2])
            cat = await session.get(Category, cat_id)
            if cat:
                await session.delete(cat)
                await session.commit()
                await query.edit_message_text(f"✅ Category `{cat.name}` deleted.")
            else:
                await query.edit_message_text("❌ Category not found.")
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="cat_main")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "cat_main":
            keyboard = [
                [InlineKeyboardButton("🏷️ List Categories", callback_data="cat_list")],
                [InlineKeyboardButton("➕ Add Category", callback_data="cat_add_start")],
            ]
            await query.edit_message_text("🏷️ *Category Management*\n\nOrganize your spending structure:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def acc_add_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏦 *Step 1/2: Enter account name (e.g. My Bank):*", parse_mode="Markdown")
    return INPUT_ACCOUNT_NAME

async def acc_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data["acc_name"] = name
    await update.message.reply_text(f"🏦 *Step 2/2: Enter institution for '{name}' (e.g. HSBC):*", parse_mode="Markdown")
    return INPUT_ACCOUNT_INST

async def acc_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inst = update.message.text
    name = context.user_data.get("acc_name")
    
    async with AsyncSessionLocal() as session:
        try:
            session.add(Account(name=name, institution=inst))
            await session.commit()
            await update.message.reply_text(f"✅ Account *{name}* added\.", parse_mode="MarkdownV2")
        except Exception as e:
            await session.rollback()
            await update.message.reply_text(f"❌ Error: {str(e)}")
    return ConversationHandler.END

async def cat_add_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏷️ *Step 1/3: Enter category name (e.g. Coffee):*", parse_mode="Markdown")
    return INPUT_CATEGORY_NAME

async def cat_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data["cat_name"] = name
    
    keyboard = [
        [InlineKeyboardButton("📉 Expense", callback_data="cat_type_expense")],
        [InlineKeyboardButton("📈 Income", callback_data="cat_type_income")]
    ]
    await update.message.reply_text(f"🏷️ *Step 2/3: Select type for '{name}':*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return INPUT_CATEGORY_TYPE

async def cat_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    ctype = query.data.split("_")[2]
    context.user_data["cat_type"] = ctype
    
    await query.edit_message_text("🏷️ *Step 3/3: Enter parent category (or 'none'):*", parse_mode="Markdown")
    return INPUT_CATEGORY_PARENT

async def cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parent = update.message.text
    if parent.lower() == "none":
        parent = None
    name = context.user_data.get("cat_name")
    ctype = context.user_data.get("cat_type")
    
    async with AsyncSessionLocal() as session:
        try:
            session.add(Category(name=name, parent_name=parent, type=ctype))
            await session.commit()
            label = f"{parent} > {name}" if parent else name
            await update.message.reply_text(f"✅ Category *{label}* added\.", parse_mode="MarkdownV2")
        except Exception as e:
            await session.rollback()
            await update.message.reply_text(f"❌ Error: {str(e)}")
    return ConversationHandler.END

async def rb_add_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📚 Knowledge Chunk", callback_data="rb_type_k")],
        [InlineKeyboardButton("🎯 Fine-Tune Example", callback_data="rb_type_e")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="rb_main")]
    ]
    await query.edit_message_text("📄 *Step 1/2: Select entry type:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_RULEBOOK_TYPE

async def handle_nl_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE, intent_data: dict):
    intent = intent_data.get("intent")
    entities = intent_data.get("entities", {})
    
    if intent == "ADD_ACCOUNT":
        context.user_data["nl_action"] = "ADD_ACCOUNT"
        if entities.get("name"):
            context.user_data["nl_data"] = {"name": entities["name"]}
            await update.message.reply_text(f"🏦 *Adding account '{entities['name']}'.*\nWhat is the institution name?")
            context.user_data["nl_state"] = "WAIT_INST"
        else:
            context.user_data["nl_data"] = {}
            await update.message.reply_text("🏦 *Account Creation:* What's the name of the account?")
            context.user_data["nl_state"] = "WAIT_NAME"
            
    elif intent == "ADD_CATEGORY":
        context.user_data["nl_action"] = "ADD_CATEGORY"
        if entities.get("name"):
            context.user_data["nl_data"] = {"name": entities["name"]}
            keyboard = [[InlineKeyboardButton("📉 Expense", callback_data="cat_nl_expense")], [InlineKeyboardButton("📈 Income", callback_data="cat_nl_income")]]
            await update.message.reply_text(f"🏷️ *Adding category '{entities['name']}'.*\nIs it an Expense or Income?", reply_markup=InlineKeyboardMarkup(keyboard))
            context.user_data["nl_state"] = "WAIT_TYPE"
        else:
            context.user_data["nl_data"] = {}
            await update.message.reply_text("🏷️ *Category Creation:* What's the name?")
            context.user_data["nl_state"] = "WAIT_NAME"

    elif intent == "ADD_TRANSACTION":
        context.user_data["nl_action"] = "ADD_TRANSACTION"
        if entities.get("amount") and entities.get("description"):
            context.user_data["nl_data"] = {"amount": float(entities["amount"]), "description": entities["description"]}
            # Pick account
            async with AsyncSessionLocal() as session:
                accounts = await list_accounts(session)
                keyboard = [[InlineKeyboardButton(acc.name, callback_data=f"tx_nl_acc_{acc.name}")] for acc in accounts]
                await update.message.reply_text(
                    f"💰 *Logging Transaction:* `{entities['amount']:.2f}` for `{entities['description']}`\n🏦 _Which account was this from?_ ",
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data["nl_state"] = "WAIT_ACC"
        else:
            context.user_data["nl_data"] = {}
            await update.message.reply_text("💰 *New Transaction:* Please tell me the amount and what it was for (e.g. '50 for dinner')")
            context.user_data["nl_state"] = "WAIT_DETAILS"

    elif intent == "LIST_ACCOUNTS":
        return await accounts_command(update, context)
    elif intent == "LIST_CATEGORIES":
        return await categories_command(update, context)
    elif intent == "LIST_RULEBOOK":
        return await rulebook_command(update, context)
    elif intent == "REVIEW_QUEUE":
        return await review_command(update, context)
    elif intent == "MODIFY_TRANSACTION":
        tx_id = entities.get("transaction_id")
        if tx_id:
            async with AsyncSessionLocal() as session:
                tx = await session.get(Transaction, int(tx_id))
                if tx:
                    await review_single_transaction(update, context, tx, session)
                else:
                    await update.message.reply_text(f"❌ Transaction `{tx_id}` not found.")
        else:
            await update.message.reply_text("📋 Which transaction would you like to modify? (Please provide the ID)")
            
    return None

async def nl_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("cat_nl_"):
        ctype = data.split("_")[2] # expense or income
        context.user_data["nl_data"]["type"] = ctype
        context.user_data["nl_state"] = "WAIT_PARENT"
        await query.edit_message_text(f"🏷️ Selected: *{ctype.title()}*.\nWho is the parent category? (or reply 'None')", parse_mode="Markdown")
        
    elif data.startswith("tx_nl_acc_"):
        acc_name = data.replace("tx_nl_acc_", "")
        context.user_data["nl_data"]["account"] = acc_name
        
        # Next step: Category selection via AI
        amount = context.user_data["nl_data"]["amount"]
        desc = context.user_data["nl_data"]["description"]
        
        await query.edit_message_text(f"💰 Account: *{acc_name}*.\n🧠 Thinking of a category...", parse_mode="Markdown")
        
        async with AsyncSessionLocal() as session:
            ai = CategorizerAI()
            candidates = await ai.suggest_category_candidates(desc, session, min_candidates=5)
            context.user_data["candidates"] = candidates
            
            msg = f"🏷️ *Suggested Categories* for '{desc}':\n\n"
            for i, c in enumerate(candidates, 1):
                cid = c['id']
                r = await session.execute(select(Category).where(Category.id == cid))
                cat = r.scalar_one_or_none()
                cat_path = f"{cat.parent_name} > {cat.name}" if cat and cat.parent_name else (cat.name if cat else f"ID {cid}")
                msg += f"{i}. {cat_path} ({c['type']}) - {c['confidence']*100:.0f}%\n"
            
            msg += "\n*Reply with the number (e.g. 1)*"
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")
            context.user_data["nl_state"] = "WAIT_CAT_NUM"

async def nl_cat_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    candidates = context.user_data.get("candidates", [])
    nl_data = context.user_data.get("nl_data", {})
    
    try:
        selection = int(text)
        if 1 <= selection <= len(candidates):
            choice = candidates[selection - 1]
            cat_id = choice.get('id')
            
            async with AsyncSessionLocal() as session:
                from datetime import datetime
                success, msg, tx = await add_transaction(
                    session,
                    date=datetime.now(),
                    amount=nl_data["amount"],
                    description=nl_data["description"],
                    account_name=nl_data["account"],
                    category_id=cat_id,
                    tx_type=choice.get('type', 'expense'),
                    decision_reason=choice.get('reasoning', 'NL Flow'),
                    confidence=choice.get('confidence', 1.0)
                )
                if success:
                    cat_name = choice.get('reasoning', 'Categorized') # fallback
                    await update.message.reply_text(f"✅ Transaction Saved!\n💰 {nl_data['amount']:.2f} | {nl_data['description']}\n🏦 {nl_data['account']}")
                    context.user_data.clear()
                else:
                    await update.message.reply_text(f"❌ Error: {msg}")
        else:
            await update.message.reply_text(f"Please enter a number between 1 and {len(candidates)}.")
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

async def rb_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    rb_type = query.data.split("_")[2] # k or e
    context.user_data["rb_type"] = rb_type
    
    label = "Knowledge (General Rule)" if rb_type == "k" else "Training Example (Prompt/Response)"
    await query.edit_message_text(
        f"✍️ *Step 2/2: Provide Content*\n\n"
        f"Selected: `{label}`\n\n"
        "Please message the text you'd like to add\.",
        parse_mode="MarkdownV2"
    )
    return INPUT_RULEBOOK_TEXT

async def rb_save_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    rb_type = context.user_data.get("rb_type")
    
    async with AsyncSessionLocal() as session:
        if rb_type == "k":
             from src.local_llm import LocalLLMPipeline
             import json
             llm = LocalLLMPipeline()
             # We need embedding. reindex_transactions is the one that does it normally.
             # We'll do it manually here for a single chunk.
             vector = await llm._embed_text(text)
             chunk = LLMKnowledgeChunk(
                 source_type="manual",
                 source_id=0,
                 content=text,
                 embedding_model=llm.embedding_model,
                 embedding_vector=json.dumps(vector) if vector else "[]"
             )
             session.add(chunk)
        else:
             example = LLMFineTuneExample(
                 source_transaction_id=0, # 0 means manual/synthetic
                 prompt=text,
                 response="User-defined behavior"
             )
             session.add(example)
        
        await session.commit()
        await update.message.reply_text("✅ Rulebook entry saved and successfully indexed.")
    return ConversationHandler.END

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
    keyboard = [
        [InlineKeyboardButton("📁 List Accounts", callback_data="acc_list")],
        [InlineKeyboardButton("➕ Add Account", callback_data="acc_add_start")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📁 *Account Management*\n\nManage your financial institutions:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏷️ List Categories", callback_data="cat_list")],
        [InlineKeyboardButton("➕ Add Category", callback_data="cat_add_start")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🏷️ *Category Management*\n\nOrganize your spending structure:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

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

async def review_single_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE, tx: Transaction, session):
    """Common logic to display a transaction for review/editing."""
    # Format Message
    cat_str = "Uncategorized"
    if tx.category:
        cat_str = f"{tx.category.parent_name} > {tx.category.name}"
    elif tx.type == "transfer":
        cat_str = "Transfer"
        
    def e(s):
        return html.escape(str(s))

    msg = (
        f"🔎 <b>Review Transaction ID: {e(tx.id)}</b>\n"
        f"📅 {e(tx.date.strftime('%Y-%m-%d'))}\n"
        f"🏦 {e(tx.account.name if tx.account else 'Unknown')}\n"
        f"📝 <b>{e(tx.description)}</b>\n"
        f"💰 <b>{tx.amount:.2f}</b>\n"
        f"🏷️ {e(cat_str)} <code>({e(tx.type)})</code>\n"
        f"🤖 Conf: {tx.confidence_score:.2f} | Rsn: {e(tx.decision_reason or 'None')}"
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
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches one pending transaction and shows it."""
    async with AsyncSessionLocal() as session:
        # Get one high priority item
        queue = await get_queue_transactions(session, limit=1)
        if not queue:
            await update.message.reply_text("✅ Review Queue is empty!")
            return
        
        await review_single_transaction(update, context, queue[0], session)

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
                    tx_type=tx_type
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
    Handle natural language actions and questions.
    """
    user_text = update.message.text
    if not user_text:
        return

    # Check for active conversational state
    nl_action = context.user_data.get("nl_action")
    nl_state = context.user_data.get("nl_state")
    nl_data = context.user_data.get("nl_data", {})

    if nl_action and nl_state:
        # Handle the next step in the conversational flow
        if nl_action == "ADD_ACCOUNT":
            if nl_state == "WAIT_NAME":
                nl_data["name"] = user_text
                context.user_data["nl_state"] = "WAIT_INST"
                await update.message.reply_text(f"🏦 Got it, '{user_text}'. What's the institution name?")
                return
            elif nl_state == "WAIT_INST":
                inst = user_text
                name = nl_data["name"]
                async with AsyncSessionLocal() as session:
                    session.add(Account(name=name, institution=inst))
                    await session.commit()
                await update.message.reply_text(f"✅ Awesome! I've added the <b>{html.escape(name)}</b> ({html.escape(inst)}) account for you.", parse_mode="HTML")
                context.user_data.clear()
                return

        elif nl_action == "ADD_CATEGORY":
            if nl_state == "WAIT_NAME":
                nl_data["name"] = user_text
                context.user_data["nl_state"] = "WAIT_TYPE"
                keyboard = [[InlineKeyboardButton("📉 Expense", callback_data="cat_nl_expense")], [InlineKeyboardButton("📈 Income", callback_data="cat_nl_income")]]
                await update.message.reply_text(f"🏷️ Okay, category '{html.escape(user_text)}'. Is this an Expense or Income?", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            elif nl_state == "WAIT_PARENT":
                parent = None if user_text.lower() == "none" else user_text
                name, ctype = nl_data["name"], nl_data["type"]
                async with AsyncSessionLocal() as session:
                    session.add(Category(name=name, parent_name=parent, type=ctype))
                    await session.commit()
                label = f"{parent} > {name}" if parent else name
                await update.message.reply_text(f"✅ Done! Category <b>{html.escape(label)}</b> added.", parse_mode="HTML")
                context.user_data.clear()
                return

        elif nl_action == "ADD_TRANSACTION":
            if nl_state == "WAIT_DETAILS":
                # Re-run intent classification on details
                intent_ai = IntentAI()
                res = await intent_ai.classify(user_text)
                ent = res.get("entities", {})
                if ent.get("amount") and ent.get("description"):
                    nl_data["amount"] = float(ent["amount"])
                    nl_data["description"] = ent["description"]
                    async with AsyncSessionLocal() as session:
                        accounts = await list_accounts(session)
                        keyboard = [[InlineKeyboardButton(acc.name, callback_data=f"tx_nl_acc_{acc.name}")] for acc in accounts]
                        await update.message.reply_text(f"💰 Logged: {nl_data['amount']:.2f} for {nl_data['description']}.\n🏦 Which bank account?", reply_markup=InlineKeyboardMarkup(keyboard))
                    context.user_data["nl_state"] = "WAIT_ACC"
                    return
                else:
                    await update.message.reply_text("I'm sorry, I couldn't understand the amount and description. Try '50 for sushi'.")
                    return
            elif nl_state == "WAIT_CAT_NUM":
                return await nl_cat_number_handler(update, context)

    # No active state, or intent changed
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # 1. Intent Classification
    intent_ai = IntentAI()
    intent_data = await intent_ai.classify(user_text)
    
    if intent_data.get("confidence", 0) > 0.7:
        await handle_nl_dispatch(update, context, intent_data)
        return

    # 2. RAG Fallback
    async with AsyncSessionLocal() as session:
        llm = LocalLLMPipeline()
        try:
             result = await llm.answer(session, user_text, top_k=5)
             answer = result["answer"]
             sources = []
             for ctx in result.get("contexts", [])[:3]:
                 content_preview = ctx['content'].split('\n')[2]
                 sources.append(f"- {content_preview}")
             
             reply = f"{html.escape(answer)}"
             if sources:
                 reply += "\n\n<b>Sources:</b>\n" + "\n".join([f"- {html.escape(s)}" for s in sources])
             if len(reply) > 4000:
                reply = reply[:4000] + "..."
             await update.message.reply_text(reply, parse_mode="HTML")
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
        BotCommand("rulebook", "Manage AI categorization rules"),
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
    app.add_handler(CommandHandler("rulebook", rulebook_command))
    app.add_handler(CommandHandler("accounts", accounts_command))
    app.add_handler(CommandHandler("categories", categories_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("reindex", reindex_command))
    
    # Review Callbacks
    app.add_handler(CallbackQueryHandler(review_callback, pattern="^rev_"))
    app.add_handler(CallbackQueryHandler(set_category_callback, pattern="^setcat_"))
    app.add_handler(CallbackQueryHandler(rulebook_callback, pattern="^rb_(list|del|main)"))
    app.add_handler(CallbackQueryHandler(account_callback, pattern="^acc_(list|del|main)"))
    app.add_handler(CallbackQueryHandler(category_callback, pattern="^cat_(list|del|main)"))
    app.add_handler(CallbackQueryHandler(nl_callback_handler, pattern="^(cat|tx)_nl_"))
    
    # Rulebook Add Conversation
    rb_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(rb_add_start_callback, pattern="^rb_add_start$")],
        states={
            SELECT_RULEBOOK_TYPE: [CallbackQueryHandler(rb_type_selected, pattern="^rb_type_")],
            INPUT_RULEBOOK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rb_save_entry)],
        },
        fallbacks=[CallbackQueryHandler(rulebook_callback, pattern="^rb_main$")],
    )
    app.add_handler(rb_conv_handler)
    
    # Account Add Conversation
    acc_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(acc_add_start_callback, pattern="^acc_add_start$")],
        states={
            INPUT_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_receive_name)],
            INPUT_ACCOUNT_INST: [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_save)],
        },
        fallbacks=[CallbackQueryHandler(account_callback, pattern="^acc_main$")],
    )
    app.add_handler(acc_conv_handler)

    # Category Add Conversation
    cat_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(cat_add_start_callback, pattern="^cat_add_start$")],
        states={
            INPUT_CATEGORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cat_receive_name)],
            INPUT_CATEGORY_TYPE: [CallbackQueryHandler(cat_type_selected, pattern="^cat_type_")],
            INPUT_CATEGORY_PARENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, cat_save)],
        },
        fallbacks=[CallbackQueryHandler(category_callback, pattern="^cat_main$")],
    )
    # Transaction Add Conversation
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
