import argparse
import asyncio
import csv
import os
from sqlalchemy.exc import IntegrityError
from src.database import init_db, AsyncSessionLocal
from src.interactive import interactive_main
from src.commands import (
    list_accounts,
    add_account,
    delete_account,
    process_import,
    rebuild_category_understanding,
    get_resettable_table_names,
    reset_selected_tables,
)
from src.local_llm import LocalLLMPipeline

async def account_command(args):
    async with AsyncSessionLocal() as session:
        if args.list:
            accounts = await list_accounts(session)
            if not accounts:
                print("No accounts found.")
            else:
                print("Accounts:")
                for acc in accounts:
                    print(f" - {acc.name} ({acc.institution})")
        elif args.add:
            success, msg = await add_account(session, args.add, args.add)
            print(msg)
        elif args.delete:
            success, msg = await delete_account(session, args.delete)
            print(msg)

async def convert_command(args):
    async with AsyncSessionLocal() as session:
        success, msg = await process_import(session, args.bank, args.input, args.account, args.output)
        print(msg)


async def llm_command(args):
    pipeline = LocalLLMPipeline(chat_model=args.model, embedding_model=args.embedding_model)
    async with AsyncSessionLocal() as session:
        if args.llm_action == "reindex":
            stats = await pipeline.reindex_transactions(session)
            print(
                f"Indexed transactions. total={stats['total']} created={stats['created']} "
                f"updated={stats['updated']} skipped={stats['skipped']}"
            )
        elif args.llm_action == "ask":
            result = await pipeline.answer(session, args.query, top_k=args.top_k)
            print(result["answer"])
            if args.show_context:
                print("\n--- Retrieved Context ---")
                for item in result["contexts"]:
                    print(f"score={item['score']:.4f}, transaction_id={item['transaction_id']}")
                    print(item["content"])
                    print("")
        elif args.llm_action == "skill-add":
            success, msg = await pipeline.add_skill(
                session,
                name=args.name,
                instruction=args.instruction,
                description=args.description,
                priority=args.priority,
            )
            print(msg)
        elif args.llm_action == "skill-list":
            skills = await pipeline.list_skills(session, active_only=args.active_only)
            if not skills:
                print("No skills found.")
                return
            for s in skills:
                print(
                    f"- {s.name} (active={s.is_active}, priority={s.priority})\n"
                    f"  description: {s.description or ''}\n"
                    f"  instruction: {s.instruction}"
                )
        elif args.llm_action == "skill-enable":
            _, msg = await pipeline.set_skill_active(session, args.name, True)
            print(msg)
        elif args.llm_action == "skill-disable":
            _, msg = await pipeline.set_skill_active(session, args.name, False)
            print(msg)
        elif args.llm_action == "export-finetune":
            stats = await pipeline.export_finetune_jsonl(session, args.output)
            print(f"Exported {stats['examples']} examples to {stats['output_path']}")
        elif args.llm_action == "rebuild-category-understanding":
            count = await rebuild_category_understanding(session)
            await session.commit()
            print(f"Rebuilt category understanding profiles for {count} categories.")


async def db_command(args):
    async with AsyncSessionLocal() as session:
        if args.db_action == "list-tables":
            print("Resettable tables:")
            for name in get_resettable_table_names():
                print(f"- {name}")
        elif args.db_action == "reset":
            selected = get_resettable_table_names() if args.all else args.tables
            ok, msg = await reset_selected_tables(session, selected)
            print(msg)


async def main():
    parser = argparse.ArgumentParser(description="Financial CLI V2")
    subparsers = parser.add_subparsers(dest="command")
    
    # Account
    acc_parser = subparsers.add_parser("account")
    group = acc_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--add", help="Name")
    group.add_argument("--delete", help="Name")
    
    # Convert/Import
    conv_parser = subparsers.add_parser("convert")
    conv_parser.add_argument("--bank", required=True)
    conv_parser.add_argument("--input", required=True)
    conv_parser.add_argument("--account", required=True)
    conv_parser.add_argument("--output", help="Optional output CSV")

    # Local LLM pipeline
    llm_parser = subparsers.add_parser("llm")
    llm_parser.add_argument("--model", default="llama3.1:8b", help="Local chat model name")
    llm_parser.add_argument("--embedding-model", default="nomic-embed-text", help="Embedding model name")
    llm_subparsers = llm_parser.add_subparsers(dest="llm_action", required=True)

    llm_reindex = llm_subparsers.add_parser("reindex")

    llm_ask = llm_subparsers.add_parser("ask")
    llm_ask.add_argument("--query", required=True)
    llm_ask.add_argument("--top-k", type=int, default=8)
    llm_ask.add_argument("--show-context", action="store_true")

    llm_skill_add = llm_subparsers.add_parser("skill-add")
    llm_skill_add.add_argument("--name", required=True)
    llm_skill_add.add_argument("--instruction", required=True)
    llm_skill_add.add_argument("--description", default="")
    llm_skill_add.add_argument("--priority", type=int, default=100)

    llm_skill_list = llm_subparsers.add_parser("skill-list")
    llm_skill_list.add_argument("--active-only", action="store_true")

    llm_skill_enable = llm_subparsers.add_parser("skill-enable")
    llm_skill_enable.add_argument("--name", required=True)

    llm_skill_disable = llm_subparsers.add_parser("skill-disable")
    llm_skill_disable.add_argument("--name", required=True)

    llm_export = llm_subparsers.add_parser("export-finetune")
    llm_export.add_argument("--output", default="data/finetune/transactions_train.jsonl")

    llm_rebuild_cat = llm_subparsers.add_parser("rebuild-category-understanding")

    # Database table maintenance
    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_action", required=True)

    db_list = db_subparsers.add_parser("list-tables")

    db_reset = db_subparsers.add_parser("reset")
    db_reset_group = db_reset.add_mutually_exclusive_group(required=True)
    db_reset_group.add_argument("--all", action="store_true", help="Reset all resettable tables")
    db_reset_group.add_argument(
        "--tables",
        nargs="+",
        help="Table names to reset. Use `python3 main.py db list-tables` to view options.",
    )

    args = parser.parse_args()
    
    await init_db()
    
    if not args.command:
        # Launch Interactive Mode if no args
        await interactive_main()
    elif args.command == "account":
        await account_command(args)
    elif args.command == "convert":
        await convert_command(args)
    elif args.command == "llm":
        await llm_command(args)
    elif args.command == "db":
        await db_command(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())
