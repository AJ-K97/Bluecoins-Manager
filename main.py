import argparse
import asyncio
import csv
import os
from sqlalchemy.exc import IntegrityError
from src.database import init_db, AsyncSessionLocal
from src.interactive import interactive_main
from src.commands import list_accounts, add_account, delete_account, process_import

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

    args = parser.parse_args()
    
    await init_db()
    
    if not args.command:
        # Launch Interactive Mode if no args
        await interactive_main()
    elif args.command == "account":
        await account_command(args)
    elif args.command == "convert":
        await convert_command(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())