import os
import re

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bank_config import list_bank_names, load_banks_payload, upsert_bank_format
from src.chat import FinanceChatAI
from src.commands import (
    export_to_bluecoins_csv,
    get_all_accounts,
    process_import,
)
from src.parser import BankParser, format_pdf_blocks_report, format_pdf_debug_report
from src.database import Transaction

from .review import import_review_callback, review_transactions
from .ui import _Ansi, _err, _info, _ok, _render_menu_view, _style, _warn


def _date_regex_hint_from_format(fmt):
    tokens = {
        "%d": r"\d{1,2}",
        "%m": r"\d{1,2}",
        "%Y": r"\d{4}",
        "%y": r"\d{2}",
        "%b": r"[A-Za-z]{3}",
        "%B": r"[A-Za-z]+",
    }
    out = re.escape(fmt)
    for token, repl in tokens.items():
        out = out.replace(re.escape(token), repl)
    out = out.replace(r"\ ", r"\s+")
    return out


def _build_guided_pdf_regex():
    date_pattern = r"\d{1,2}\s+[A-Za-z]{3}"
    amount_pattern = r"\$?[\d,]+\.\d{2}"
    return rf"^({date_pattern})\s+(.+?)\s+({amount_pattern})?\s*({amount_pattern})?\s+{amount_pattern}$"


async def import_wizard(session):
    _render_menu_view(
        path="Home / Import Transactions",
        summary_lines=[
            "Load CSV/PDF data, run categorization, then review and export.",
        ],
        tips_lines=[
            "If importing PDF, inspect parsed text/blocks before committing.",
            "You can review each transaction during import or do bulk review after.",
            "Export generated transactions to Bluecoins CSV at the end.",
        ],
    )
    bank_names = list_bank_names()
    if not bank_names:
        _warn("No bank formats configured. Please add one via 'Manage Bank Formats'.")
        return

    bank = await inquirer.select(
        message="Select Bank Format:",
        choices=bank_names + [Choice(value=None, name="Cancel")],
    ).execute_async()

    if not bank:
        return

    file_path = await inquirer.filepath(
        message="Path to CSV/PDF file:",
        default=os.getcwd(),
        validate=lambda x: os.path.isfile(x) and x.lower().endswith((".csv", ".pdf")),
        only_files=True,
    ).execute_async()

    if not file_path:
        return

    if file_path.lower().endswith(".pdf"):
        inspect_now = await inquirer.confirm(
            message="Inspect PDF text/blocks before importing?",
            default=True,
        ).execute_async()
        if inspect_now:
            await inspect_pdf_text_menu(default_file_path=file_path, default_bank=bank)

    accounts = await get_all_accounts(session)
    if not accounts:
        _warn("No accounts found. Please create one first.")
        return

    choices = [Choice(value=acc.name, name=acc.name) for acc in accounts]
    account_name = await inquirer.select(message="Associate with Account:", choices=choices).execute_async()

    do_interactive_review = await inquirer.confirm(
        message="Review each transaction as it is processed?"
    ).execute_async()
    callback = import_review_callback if do_interactive_review else None

    _info("\nProcessing... (This may take a moment for AI categorization)\n")
    success, msg, new_txs = await process_import(
        session, bank, file_path, account_name, review_callback=callback
    )

    if success:
        _ok(f"\nSuccess: {msg}\n")

        if new_txs and not do_interactive_review:
            do_review = await inquirer.confirm(message="Review and Verify these transactions now?").execute_async()
            if do_review:
                await review_transactions(session, new_txs)
    else:
        _err(f"\nError: {msg}\n")
        return

    do_export = await inquirer.confirm(message="Export to Bluecoins CSV now?").execute_async()
    if do_export:
        output_path = await inquirer.filepath(
            message="Output Path:",
            default="bluecoins_import.csv",
            validate=lambda x: not os.path.isdir(x),
        ).execute_async()

        tx_ids = [t.id for t in new_txs] if new_txs else []
        if tx_ids:
            stmt = select(Transaction).options(
                selectinload(Transaction.category), selectinload(Transaction.account)
            ).where(Transaction.id.in_(tx_ids))
            res = await session.execute(stmt)
            final_txs = res.scalars().all()

            success, msg = export_to_bluecoins_csv(final_txs, output_path)
            (_ok if success else _err)(msg)


async def bank_format_builder_menu():
    _render_menu_view(
        path="Home / Bank Formats",
        summary_lines=[
            "Configure parser mappings for CSV and PDF statements.",
        ],
        tips_lines=[
            "Use guided PDF mode for debit/credit + balance style statements.",
            "Keep multiple date formats to support mixed bank exports.",
        ],
    )
    payload = load_banks_payload()
    existing = sorted(payload["banks"].keys())

    bank_name = await inquirer.text(message="Bank name to add/update (e.g. ANZ):").execute_async()
    bank_name = (bank_name or "").strip()
    if not bank_name:
        return

    if bank_name in existing:
        overwrite = await inquirer.confirm(
            message=f"Bank '{bank_name}' already exists. Overwrite format?"
        ).execute_async()
        if not overwrite:
            return

    source_mode = await inquirer.select(
        message="What input format should this bank support?",
        choices=[
            Choice(value="csv", name="CSV only"),
            Choice(value="pdf", name="PDF only"),
            Choice(value="both", name="CSV and PDF"),
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()
    if not source_mode:
        return

    date_formats_raw = await inquirer.text(
        message="Date formats (comma-separated strptime patterns):",
        default="%d %b %Y,%d/%m/%Y,%Y-%m-%d,%d-%m-%Y,%d %b",
    ).execute_async()
    date_formats = [x.strip() for x in (date_formats_raw or "").split(",") if x.strip()]
    if not date_formats:
        date_formats = ["%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]

    cfg = {"date_formats": date_formats}

    if source_mode in {"csv", "both"}:
        _info("\nCSV mapping\n-----------")
        cfg["date_column"] = await inquirer.text(message="Date column name:").execute_async()
        cfg["description_column"] = await inquirer.text(message="Description column name:").execute_async()
        cfg["amount_column"] = await inquirer.text(message="Amount column name:").execute_async()

        type_mode = await inquirer.select(
            message="How should transaction type be inferred?",
            choices=[
                Choice(value="amount_sign", name="Use amount sign (+/-)"),
                Choice(value="direction_column", name="Use direction column (IN/OUT etc.)"),
            ],
        ).execute_async()
        cfg["type_determination"] = type_mode
        cfg["negate_amounts"] = await inquirer.confirm(
            message="Negate parsed amounts? (for statements where signs are reversed)",
            default=False,
        ).execute_async()

        if type_mode == "direction_column":
            cfg["direction_column"] = await inquirer.text(message="Direction column name:").execute_async()
            cfg["direction_in_value"] = await inquirer.text(message="Incoming value (e.g. IN):").execute_async()
            cfg["direction_out_value"] = await inquirer.text(message="Outgoing value (e.g. OUT):").execute_async()

    if source_mode in {"pdf", "both"}:
        _info("\nPDF mapping\n-----------")
        pdf_mode = await inquirer.select(
            message="PDF parse mode",
            choices=[
                Choice(value="guided_debit_credit", name="Guided: Date + Description + Credit/Debit + Balance"),
                Choice(value="manual_regex", name="Manual regex"),
            ],
        ).execute_async()

        if pdf_mode == "guided_debit_credit":
            cfg["pdf_regex"] = _build_guided_pdf_regex()
            cfg["pdf_date_group"] = 1
            cfg["pdf_description_group"] = 2
            cfg["pdf_credit_group"] = 3
            cfg["pdf_debit_group"] = 4
            cfg["pdf_prefer_debit_when_single_amount"] = await inquirer.confirm(
                message="If only one amount is found, treat it as Debit (expense)?",
                default=False,
            ).execute_async()
            _ok("Generated regex for split credit/debit PDF lines.")
        else:
            default_date_re = (
                _date_regex_hint_from_format(date_formats[0])
                if date_formats
                else r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}"
            )
            default_regex = rf"^({default_date_re})\s+(.+?)\s+(-?\$?[\d,]+\.\d{{2}})$"
            cfg["pdf_regex"] = await inquirer.text(
                message="Regex with groups: date(1), description(2), amount(3)",
                default=default_regex,
            ).execute_async()
            cfg["pdf_date_group"] = 1
            cfg["pdf_description_group"] = 2
            cfg["pdf_amount_group"] = 3

    upsert_bank_format(bank_name, cfg)
    _ok(f"\nSaved bank format '{bank_name}' to data/banks_config.json\n")
    print(_style(str(cfg), _Ansi.DIM))

    if bank_name.upper() == "ANZ":
        print(
            "\nANZ tip: for lines like '29 Jan ... Credit Debit Balance', use the guided PDF mode.\n"
            "Keep '%d %b' in date formats; the parser can infer the year from text like 'Effective Date 27/01/2026'.\n"
        )


async def chat_wizard(session):
    _render_menu_view(
        path="Home / Finance Chat",
        summary_lines=[
            "Ask natural-language questions about your transactions.",
            "Type 'exit' or 'q' to return.",
        ],
        tips_lines=[
            "Ask specific questions: categories, periods, top spenders, trends.",
            "Chat runs read-only SQL generation for safe insights.",
        ],
    )

    chat_ai = FinanceChatAI()

    while True:
        question = await inquirer.text(message="You:").execute_async()
        if question.lower() in ["exit", "quit", "q"]:
            break

        _info("Thinking...")
        response = await chat_ai.chat(question, session)
        print(_style("\nAI:", _Ansi.BOLD, _Ansi.MAGENTA) + f" {response}\n")


async def inspect_pdf_text_menu(default_file_path=None, default_bank=None):
    _render_menu_view(
        path="Home / PDF Inspect",
        summary_lines=[
            "Preview parsed statement text and export full debug reports.",
        ],
        tips_lines=[
            "Use blocks mode for multiline transaction assembly validation.",
            "Export full report to compare parser tweaks over time.",
        ],
    )
    file_path = default_file_path
    if not file_path:
        file_path = await inquirer.filepath(
            message="Path to PDF file:",
            default=os.getcwd(),
            validate=lambda x: os.path.isfile(x) and x.lower().endswith(".pdf"),
            only_files=True,
        ).execute_async()
    if not file_path:
        return

    mode = await inquirer.select(
        message="Display mode:",
        choices=[
            Choice(value="both", name="Raw + Cleaned (default)"),
            Choice(value="raw", name="Raw only"),
            Choice(value="cleaned", name="Cleaned only"),
            Choice(value="blocks", name="Blocks (assembled multiline transactions)"),
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()
    if not mode:
        return

    preview_label = "Max preview blocks:" if mode == "blocks" else "Max preview lines:"
    max_lines_raw = await inquirer.text(
        message=preview_label,
        default="500",
        validate=lambda x: (x or "").strip().isdigit() and int((x or "").strip()) > 0,
        invalid_message="Enter a positive integer.",
    ).execute_async()
    max_lines = int((max_lines_raw or "500").strip())

    parser = BankParser()
    report_preview = None
    full_report = None
    try:
        if mode == "blocks":
            bank_name = default_bank
            if not bank_name:
                bank_name = await inquirer.select(
                    message="Select bank format for block assembly:",
                    choices=list_bank_names() + [Choice(value=None, name="Cancel")],
                ).execute_async()
            if not bank_name:
                return
            blocks_data = parser.extract_pdf_blocks_debug(file_path, bank_name)
            report_preview = format_pdf_blocks_report(blocks_data, max_blocks=max_lines)
            full_report = format_pdf_blocks_report(blocks_data, max_blocks=None)
        else:
            debug_data = parser.extract_pdf_debug(file_path, apply_cleaning=True)
            report_preview = format_pdf_debug_report(debug_data, mode=mode, max_lines=max_lines)
            full_report = format_pdf_debug_report(debug_data, mode=mode, max_lines=None)
    except Exception as e:
        _err(f"\nError: {e}\n")
        return

    print("\n" + report_preview)

    do_export = await inquirer.confirm(message="Export full report to .txt file?").execute_async()
    if not do_export:
        return

    output_path = await inquirer.filepath(
        message="Output path:",
        default="pdf_debug_report.txt",
        validate=lambda x: not os.path.isdir(x),
    ).execute_async()
    if not output_path:
        return

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_report)
    _ok(f"\nSaved full debug report to {output_path}\n")
