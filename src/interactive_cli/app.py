from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator
from sqlalchemy import func, select

from src.commands import get_all_categories, get_queue_stats, list_accounts, seed_reference_data
from src.database import AsyncSessionLocal, Transaction, init_db

from .menus import (
    manage_accounts_menu,
    manage_categories_menu,
    manage_global_rulebook_menu,
    manage_transactions_menu,
    reset_database_menu,
)
from .ui import _menu_panel
from .workflows import bank_format_builder_menu, chat_wizard, import_wizard, inspect_pdf_text_menu


async def _main_menu_snapshot(session):
    accounts = await list_accounts(session)
    categories = await get_all_categories(session)
    total_tx = int(await session.scalar(select(func.count(Transaction.id))) or 0)
    verified_tx = int(
        await session.scalar(select(func.count(Transaction.id)).where(Transaction.is_verified.is_(True)))
        or 0
    )
    unverified_tx = max(total_tx - verified_tx, 0)

    queue_rows = await get_queue_stats(session)
    needs_review = int(
        sum(
            int(count or 0)
            for state, _bucket, count in queue_rows
            if (state or "") in {"needs_review", "force_review"}
        )
    )

    return {
        "accounts": len(accounts),
        "categories": len(categories),
        "total_tx": total_tx,
        "verified_tx": verified_tx,
        "unverified_tx": unverified_tx,
        "needs_review": needs_review,
    }


def _main_menu_message(stats):
    width = 86
    border = "+" + "-" * (width - 2) + "+"
    title = " Bluecoins Manager  |  Interactive CLI "
    title_pad = max((width - 2 - len(title)) // 2, 0)
    title_line = "|" + (" " * title_pad) + title + (" " * (width - 2 - title_pad - len(title))) + "|"

    def row(text=""):
        return ("| " + text).ljust(width - 1) + "|"

    lines = [
        border,
        title_line,
        row(),
        row("Data Snapshot"),
        row(),
        row(
            f"Accounts: {stats['accounts']:<5}    Categories: {stats['categories']:<5}    "
            f"Transactions: {stats['total_tx']:<8}"
        ),
        row(
            f"Verified: {stats['verified_tx']:<8}    Unverified: {stats['unverified_tx']:<8}    "
            f"Needs Review: {stats['needs_review']:<8}"
        ),
        row(),
        row("Tip: Start with 'Import Transactions', then review and verify."),
        row(),
        border,
        "Main Menu:",
        "",
    ]
    return "\n".join(lines)


async def interactive_main():
    print("Welcome to Bluecoins Manager V2")
    await init_db()

    async with AsyncSessionLocal() as session:
        _, seed_msg = await seed_reference_data(session)
        print(seed_msg)
        while True:
            stats = await _main_menu_snapshot(session)
            action = await inquirer.select(
                message=_main_menu_message(stats),
                choices=[
                    Separator("=== Workflow ==="),
                    Choice(value="import", name="Import Transactions"),
                    Choice(value="transactions", name="Review / Manage Transactions"),
                    Choice(value="chat", name="Chat with your Data"),
                    Separator(" "),
                    Separator("=== Configuration ==="),
                    Choice(value="categories", name="Manage Categories"),
                    Choice(value="accounts", name="Manage Accounts"),
                    Choice(value="banks", name="Manage Bank Formats"),
                    Choice(value="rulebook", name="Manage AI Rulebook"),
                    Separator(" "),
                    Separator("=== Tools ==="),
                    Choice(value="pdf", name="Inspect PDF Text (pypdf)"),
                    Choice(value="reset", name="Reset Database"),
                    Separator(" "),
                    Choice(value=None, name="Exit"),
                ],
            ).execute_async()

            if not action:
                print("Goodbye!")
                break

            if action == "accounts":
                await manage_accounts_menu(session)
            elif action == "import":
                await import_wizard(session)
            elif action == "transactions":
                await manage_transactions_menu(session)
            elif action == "categories":
                await manage_categories_menu(session)
            elif action == "banks":
                await bank_format_builder_menu()
            elif action == "pdf":
                await inspect_pdf_text_menu()
            elif action == "rulebook":
                await manage_global_rulebook_menu(session)
            elif action == "reset":
                await reset_database_menu(session)
            elif action == "chat":
                await chat_wizard(session)
