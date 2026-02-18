import argparse
import asyncio
import csv
import os
import json
import itertools
import sys
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from src.database import init_db, AsyncSessionLocal
from src.interactive import interactive_main, review_queue_menu
from src.parser import BankParser, format_pdf_debug_report, format_pdf_blocks_report
from src.keyword_resolver import KeywordResolver
from src.ai import CategorizerAI
from src.commands import (
    list_accounts,
    add_account,
    delete_account,
    process_import,
    rebuild_category_understanding,
    get_resettable_table_names,
    reset_selected_tables,
    get_queue_transactions,
    get_queue_stats,
    recalc_queue_decisions,
    recalc_queue_decisions,
    format_category_obj_label,
    add_transaction,
)
from src.local_llm import LocalLLMPipeline
from src.ai_config import close_ollama_client
from src.benchmark import (
    clear_benchmark_item_label,
    import_benchmark_csv,
    learn_aliases_from_benchmark,
    list_benchmark_items,
    list_benchmark_runs,
    score_benchmark_dataset,
    set_benchmark_item_label,
    set_benchmark_item_label_category_id,
)


async def _run_with_spinner(label, coro):
    spinner = itertools.cycle(["|", "/", "-", "\\"])
    task = asyncio.create_task(coro)
    try:
        while not task.done():
            if sys.stdout.isatty():
                print(f"\r{label} {next(spinner)}", end="", flush=True)
            await asyncio.sleep(0.1)
        result = await task
    finally:
        if sys.stdout.isatty():
            print("\r\033[2K", end="", flush=True)
    return result

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
        success, msg = await _run_with_spinner(
            "Importing + categorizing transactions",
            process_import(session, args.bank, args.input, args.account, args.output),
        )
        print(msg)


async def add_tx_command(args):
    async with AsyncSessionLocal() as session:
        success, msg, tx = await add_transaction(
            session,
            date=args.date,
            amount=args.amount,
            description=args.desc,
            account_name=args.account
        )
        print(msg)


async def pdf_debug_command(args):
    parser = BankParser()
    if args.as_blocks:
        bank_name = args.bank or "ANZ"
        try:
            blocks_data = parser.extract_pdf_blocks_debug(args.input, bank_name=bank_name)
        except Exception as e:
            print(f"Error: {e}")
            return
        report = format_pdf_blocks_report(blocks_data, max_blocks=args.max_blocks)
        print(report)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(format_pdf_blocks_report(blocks_data, max_blocks=None))
            print(f"Saved full block debug report to {args.output}")
        return

    mode = "both"
    if args.raw_only:
        mode = "raw"
    elif args.cleaned_only:
        mode = "cleaned"

    try:
        debug_data = parser.extract_pdf_debug(args.input, apply_cleaning=True)
    except Exception as e:
        print(f"Error: {e}")
        return

    preview_report = format_pdf_debug_report(debug_data, mode=mode, max_lines=args.max_lines)
    print(preview_report)

    if args.output:
        full_report = format_pdf_debug_report(debug_data, mode=mode, max_lines=None)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_report)
        print(f"Saved full debug report to {args.output}")


async def keyword_debug_command(args):
    description = (args.desc or "").strip()
    if not description:
        print("Error: --desc is required")
        return
    async with AsyncSessionLocal() as session:
        resolver = KeywordResolver()
        debug = await resolver.debug(session, description)
    resolved = debug["resolved_result"]
    rule = debug["rule_result"]
    print("Keyword Debug")
    print(f"- description: {debug['description']}")
    print(f"- normalized_phrase: {debug['normalized_phrase']}")
    print(f"- rule.keyword: {rule.keyword} (conf={rule.confidence:.2f}, source={rule.source})")
    print(f"- resolved.keyword: {resolved.keyword} (conf={resolved.confidence:.2f}, source={resolved.source})")
    print(f"- tokens_used: {', '.join(resolved.tokens_used) if resolved.tokens_used else 'none'}")
    matches = debug.get("exact_alias_matches") or []
    if matches:
        print("- exact_alias_matches:")
        for m in matches:
            print(
                f"  - {m['canonical_keyword']} "
                f"(support={m['support_count']}, verified={m['verified_count']})"
            )
            if args.show_sources:
                sources = []
                try:
                    payload = json.loads(m.get("metadata_json") or "{}")
                    if isinstance(payload, dict):
                        sources = payload.get("source_transactions") or []
                except Exception:
                    sources = []
                if sources:
                    print("    sources:")
                    for s in sources:
                        tx_id = s.get("transaction_id")
                        desc = (s.get("description") or "").strip()
                        print(f"      - tx_id={tx_id} | {desc}")
                else:
                    print("    sources: none")
    else:
        print("- exact_alias_matches: none")


async def category_debug_command(args):
    description = (args.desc or "").strip()
    if not description:
        print("Error: --desc is required")
        return

    tx_type = (args.tx_type or "").strip().lower()
    if tx_type not in {"expense", "income"}:
        print("Error: --tx-type must be one of: expense, income")
        return

    async with AsyncSessionLocal() as session:
        resolver = KeywordResolver()
        keyword_debug = await resolver.debug(session, description)
        ai = CategorizerAI(model=args.model)
        extra_instruction = (
            f"Debug context: transaction amount is {float(args.amount):.2f}. "
            f"Use amount direction and size as a weak hint only."
        )
        candidates = await ai.suggest_category_candidates(
            description,
            session,
            min_candidates=max(3, int(args.top_k)),
            extra_instruction=extra_instruction,
            expected_type=tx_type,
        )

    resolved = keyword_debug["resolved_result"]
    rule = keyword_debug["rule_result"]

    print("Category Debug")
    print(f"- description: {description}")
    print(f"- amount: {float(args.amount):.2f}")
    print(f"- tx_type: {tx_type}")
    print(f"- keyword.rule: {rule.keyword} (conf={rule.confidence:.2f}, source={rule.source})")
    print(
        f"- keyword.resolved: {resolved.keyword} "
        f"(conf={resolved.confidence:.2f}, source={resolved.source})"
    )
    print(
        f"- keyword.tokens_used: "
        f"{', '.join(resolved.tokens_used) if resolved.tokens_used else 'none'}"
    )

    if not candidates:
        print("- ai.decision: none")
        print("- ai.reasoning: Unable to produce category suggestions.")
        return

    top = candidates[0]
    print("- ai.top_decision:")
    print(f"  - category_id: {top['id']}")
    print(f"  - predicted_type: {top['type']}")
    print(f"  - confidence: {top['confidence']:.2f}")
    print(f"  - reasoning: {top['reasoning']}")

    print("- ai.candidates:")
    for idx, c in enumerate(candidates[: max(1, int(args.top_k))], start=1):
        print(
            f"  {idx}. category_id={c['id']} type={c['type']} "
            f"conf={c['confidence']:.2f}"
        )
        print(f"     reasoning: {c['reasoning']}")


async def keyword_backfill_command(args):
    async with AsyncSessionLocal() as session:
        resolver = KeywordResolver()
        stats = await resolver.backfill_from_verified_transactions(
            session,
            reset_existing=not args.keep_existing,
        )
    print(
        f"Keyword backfill complete. "
        f"seen_verified={stats['seen_verified']} learned_updates={stats['learned_updates']} "
        f"reset_existing={not args.keep_existing}"
    )


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


async def queue_command(args):
    async with AsyncSessionLocal() as session:
        if args.queue_action == "list":
            states = args.state if args.state else None
            rows = await get_queue_transactions(
                session,
                states=states,
                bucket=args.bucket,
                account_id=args.account_id,
                limit=args.limit,
            )
            if not rows:
                print("Queue is empty for selected filters.")
                return
            for tx in rows:
                cat = format_category_obj_label(tx.category) if tx.category else "Uncategorized > Uncategorized [unknown]"
                print(
                    f"#{tx.id} [{tx.decision_state}] [{tx.review_bucket}] "
                    f"prio={tx.review_priority} conf={tx.confidence_score or 0.0:.2f} "
                    f"{tx.date.strftime('%Y-%m-%d')} {tx.amount:.2f} | {tx.description} | {cat}"
                )
                if tx.decision_reason:
                    print(f"  reason: {tx.decision_reason}")
        elif args.queue_action == "stats":
            rows = await get_queue_stats(session)
            if not rows:
                print("No queue stats available.")
                return
            for state, bucket, count in rows:
                print(f"{state or 'none':<14} {bucket or 'none':<16} {count}")
        elif args.queue_action == "recalc":
            since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
            updated = await _run_with_spinner(
                "Recalculating review decisions",
                recalc_queue_decisions(session, since=since),
            )
            print(f"Recalculated queue decision metadata for {updated} transactions.")
        elif args.queue_action == "review":
            await review_queue_menu(session)


async def benchmark_command(args):
    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice
    from src.interactive_cli.common import TRANSFER_CHOICE, choose_category_tree

    async with AsyncSessionLocal() as session:
        if args.benchmark_action == "import-csv":
            ok, msg, _stats = await import_benchmark_csv(
                session,
                args.input,
                source_name=args.source_name,
                bank_name=args.bank,
            )
            print(msg)
            if not ok:
                return
        elif args.benchmark_action == "list":
            rows = await list_benchmark_items(
                session,
                limit=args.limit,
                unlabeled_only=args.unlabeled_only,
                source_file=args.source_file,
            )
            if not rows:
                print("No benchmark rows found.")
                return
            for row in rows:
                if row.expected_type == "transfer":
                    expected = "(Transfer) > (Transfer) [transfer]"
                elif row.expected_parent_name and row.expected_category_name and row.expected_type:
                    expected = f"{row.expected_parent_name} > {row.expected_category_name} [{row.expected_type}]"
                else:
                    expected = "UNLABELED"
                print(
                    f"#{row.id} src={row.source_file or '-'} row={row.source_row_number or '-'} "
                    f"type={row.tx_type or '-'} expected={expected} | {row.description}"
                )
        elif args.benchmark_action == "label":
            ok, msg = await set_benchmark_item_label(
                session,
                item_id=args.id,
                parent_name=args.parent,
                category_name=args.category,
                tx_type=args.type,
                set_transfer=args.set_transfer,
            )
            print(msg)
            if not ok:
                return
        elif args.benchmark_action == "score":
            def _truncate(text, size=52):
                raw = (text or "").strip()
                if len(raw) <= size:
                    return raw
                return raw[: size - 3] + "..."

            async def _progress(update):
                processed = int(update.get("processed") or 0)
                total_rows = max(1, int(update.get("total") or 1))
                pct = (processed / total_rows) * 100.0
                marker = "OK" if update.get("is_correct") else "XX"
                row_id = update.get("item_id")
                desc = _truncate(update.get("description") or "")

                if sys.stdout.isatty():
                    width = 24
                    filled = int((processed / total_rows) * width)
                    bar = "#" * filled + "-" * (width - filled)
                    line = (
                        f"[{bar}] {processed:>3}/{total_rows:<3} {pct:6.2f}% "
                        f"{marker} #{row_id} {desc}"
                    )
                    print(f"\r{line}", end="", flush=True)
                else:
                    print(
                        f"[{processed}/{total_rows}] {pct:6.2f}% {marker} "
                        f"#{row_id} {desc}"
                    )

            ok, msg, summary = await score_benchmark_dataset(
                session,
                model=args.model,
                limit=args.limit,
                source_file=args.source_file,
                progress_callback=_progress,
            )
            if sys.stdout.isatty():
                print("")
            print(msg)
            if not ok or not summary:
                return
            print(f"run_id={summary['run_id']} model={summary['model']}")
            print(
                f"overall_score={summary['overall_score']:.2f}/100 "
                f"({summary['correct']}/{summary['total']})"
            )
            print(
                f"memory_score={summary['memory_score']:.2f}/100 "
                f"coverage={summary['memory_coverage']:.2f}%"
            )
            for tx_type in ["expense", "income", "transfer"]:
                score = summary["by_type"].get(tx_type)
                score_text = f"{score:.2f}/100" if score is not None else "n/a"
                print(f"{tx_type}_score={score_text}")

            errors = summary.get("errors") or []
            if errors and args.show_errors > 0:
                print("\nTop errors:")
                for err in errors[: max(1, int(args.show_errors))]:
                    expected = err["expected"]
                    predicted = err["predicted"]
                    print(
                        f"- #{err['id']} expected={expected['type']}:{expected['label']} "
                        f"predicted={predicted['type']}:{predicted['category_id']} "
                        f"conf={predicted['confidence']:.2f}"
                    )
        elif args.benchmark_action == "runs":
            runs = await list_benchmark_runs(session, limit=args.limit)
            if not runs:
                print("No benchmark runs found.")
                return
            for run in runs:
                print(
                    f"#{run.id} {run.created_at.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"model={run.model} overall={run.overall_score:.2f}/100 "
                    f"memory={run.memory_score:.2f}/100 coverage={run.memory_coverage:.2f}% "
                    f"n={run.evaluated_items}"
                )
        elif args.benchmark_action == "learn-aliases":
            ok, msg, _stats = await learn_aliases_from_benchmark(
                session,
                source_file=args.source_file,
                limit=args.limit,
                include_transfer=args.include_transfer,
            )
            print(msg)
            if not ok:
                return
        elif args.benchmark_action == "review":
            rows = await list_benchmark_items(
                session,
                limit=args.limit,
                unlabeled_only=args.unlabeled_only,
                source_file=args.source_file,
            )
            if args.start_id:
                rows = [r for r in rows if r.id >= int(args.start_id)]
            if not rows:
                print("No benchmark rows found for interactive review.")
                return

            idx = 0
            updates = 0
            total = len(rows)
            viewed = 0
            while idx < total:
                row = rows[idx]
                viewed += 1
                if row.expected_type == "transfer":
                    expected = "(Transfer) > (Transfer) [transfer]"
                elif row.expected_parent_name and row.expected_category_name and row.expected_type:
                    expected = f"{row.expected_parent_name} > {row.expected_category_name} [{row.expected_type}]"
                else:
                    expected = "UNLABELED"

                print("")
                print(f"[{idx + 1}/{total}] Benchmark #{row.id}")
                print(f"source={row.source_file or '-'} row={row.source_row_number or '-'} external_id={row.external_id or '-'}")
                print(f"type_hint={row.tx_type or '-'} amount={row.amount if row.amount is not None else '-'} date={row.date.strftime('%Y-%m-%d') if row.date else '-'}")
                print(f"description: {row.description}")
                print(f"current label: {expected}")

                action = await inquirer.select(
                    message="Benchmark review action:",
                    choices=[
                        Choice(value="pick", name="Pick Category (tree)"),
                        Choice(value="transfer", name="Mark as Transfer"),
                        Choice(value="clear", name="Clear Current Label"),
                        Choice(value="next", name="Skip / Next"),
                        Choice(value="prev", name="Previous"),
                        Choice(value="quit", name="Quit Review"),
                    ],
                    default="pick",
                ).execute_async()

                if action == "quit":
                    break
                if action == "next":
                    idx += 1
                    continue
                if action == "prev":
                    idx = max(0, idx - 1)
                    continue
                if action == "clear":
                    ok, msg = await clear_benchmark_item_label(session, row.id)
                    print(msg)
                    if ok:
                        updates += 1
                    idx += 1
                    continue
                if action == "transfer":
                    ok, msg = await set_benchmark_item_label(session, item_id=row.id, set_transfer=True)
                    print(msg)
                    if ok:
                        updates += 1
                    idx += 1
                    continue

                selected_cat = await choose_category_tree(
                    session,
                    prompt_prefix=f"Benchmark #{row.id}",
                    default_type=row.tx_type if row.tx_type in {"income", "expense"} else None,
                    restrict_to_default_type=False,
                )
                if selected_cat is None:
                    continue
                if selected_cat == TRANSFER_CHOICE:
                    ok, msg = await set_benchmark_item_label(session, item_id=row.id, set_transfer=True)
                    print(msg)
                    if ok:
                        updates += 1
                    idx += 1
                    continue

                ok, msg = await set_benchmark_item_label_category_id(session, row.id, selected_cat.id)
                print(msg)
                if ok:
                    updates += 1
                idx += 1

            print(f"Interactive benchmark review completed. rows_seen={viewed} updates={updates}")


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

    # PDF text debug/inspection
    pdf_debug_parser = subparsers.add_parser("pdf-debug")
    pdf_debug_parser.add_argument("--input", required=True, help="Path to PDF file")
    mode_group = pdf_debug_parser.add_mutually_exclusive_group()
    mode_group.add_argument("--cleaned-only", action="store_true")
    mode_group.add_argument("--raw-only", action="store_true")
    pdf_debug_parser.add_argument("--as-blocks", action="store_true", help="Show assembled multiline transaction blocks")
    pdf_debug_parser.add_argument("--bank", help="Bank name for block assembly (default: ANZ when --as-blocks)")
    pdf_debug_parser.add_argument("--max-blocks", type=int, default=200, help="Max blocks to print in --as-blocks mode")
    pdf_debug_parser.add_argument("--output", help="Optional output .txt path for full report")
    pdf_debug_parser.add_argument("--max-lines", type=int, default=500, help="Max lines for console preview")

    keyword_debug_parser = subparsers.add_parser("keyword-debug")
    keyword_debug_parser.add_argument("--desc", required=True, help="Transaction description to analyze")
    keyword_debug_parser.add_argument(
        "--show-sources",
        action="store_true",
        help="Pretty print source transactions stored against alias matches.",
    )

    category_debug_parser = subparsers.add_parser("category-debug")
    category_debug_parser.add_argument("--desc", required=True, help="Transaction description")
    category_debug_parser.add_argument("--amount", type=float, required=True, help="Transaction amount")
    category_debug_parser.add_argument(
        "--tx-type",
        required=True,
        choices=["expense", "income"],
        help="Expected transaction type",
    )
    category_debug_parser.add_argument("--top-k", type=int, default=5, help="How many candidates to print")
    category_debug_parser.add_argument("--model", default="llama3.1:8b", help="LLM model name")

    keyword_backfill_parser = subparsers.add_parser("keyword-backfill")
    keyword_backfill_parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep existing alias rows and add/update on top (default rebuilds aliases from scratch).",
    )

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

    # Review queue
    queue_parser = subparsers.add_parser("queue")
    queue_subparsers = queue_parser.add_subparsers(dest="queue_action", required=True)

    queue_list = queue_subparsers.add_parser("list")
    queue_list.add_argument("--state", nargs="+", choices=["needs_review", "force_review", "auto_approved"])
    queue_list.add_argument("--bucket")
    queue_list.add_argument("--account-id", type=int)
    queue_list.add_argument("--limit", type=int, default=100)

    queue_stats = queue_subparsers.add_parser("stats")

    queue_recalc = queue_subparsers.add_parser("recalc")
    queue_recalc.add_argument("--since", help="YYYY-MM-DD")

    queue_review = queue_subparsers.add_parser("review")
    
    # Add Transaction
    add_tx_parser = subparsers.add_parser("add-tx")
    add_tx_parser.add_argument("--amount", type=float, required=True)
    add_tx_parser.add_argument("--desc", required=True)
    add_tx_parser.add_argument("--account", required=True)
    add_tx_parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD")

    # Benchmark dataset + scoring
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_subparsers = benchmark_parser.add_subparsers(dest="benchmark_action", required=True)

    benchmark_import = benchmark_subparsers.add_parser("import-csv")
    benchmark_import.add_argument("--input", required=True, help="Path to CSV or PDF dataset.")
    benchmark_import.add_argument("--source-name", help="Optional logical source name.")
    benchmark_import.add_argument(
        "--bank",
        help="Optional bank config name (required for PDF, optional for bank-formatted CSV like Wise).",
    )

    benchmark_list = benchmark_subparsers.add_parser("list")
    benchmark_list.add_argument("--limit", type=int, default=50)
    benchmark_list.add_argument("--unlabeled-only", action="store_true")
    benchmark_list.add_argument("--source-file", help="Filter by source name.")

    benchmark_label = benchmark_subparsers.add_parser("label")
    benchmark_label.add_argument("--id", required=True, type=int, help="Benchmark row id.")
    benchmark_label.add_argument("--parent", help="Expected parent category name.")
    benchmark_label.add_argument("--category", help="Expected sub category name.")
    benchmark_label.add_argument("--type", choices=["expense", "income"], help="Category type.")
    benchmark_label.add_argument("--set-transfer", action="store_true", help="Set expected type to transfer.")

    benchmark_score = benchmark_subparsers.add_parser("score")
    benchmark_score.add_argument("--model", default="llama3.1:8b", help="LLM model name")
    benchmark_score.add_argument("--limit", type=int, help="Evaluate first N labeled rows.")
    benchmark_score.add_argument(
        "--source-file",
        nargs="+",
        help="Filter by source name(s). Supports multiple values and comma-separated lists.",
    )
    benchmark_score.add_argument("--show-errors", type=int, default=10, help="Print first N mismatches.")

    benchmark_runs = benchmark_subparsers.add_parser("runs")
    benchmark_runs.add_argument("--limit", type=int, default=20)

    benchmark_learn_aliases = benchmark_subparsers.add_parser("learn-aliases")
    benchmark_learn_aliases.add_argument("--source-file", help="Filter by source name.")
    benchmark_learn_aliases.add_argument("--limit", type=int, help="Maximum rows to process.")
    benchmark_learn_aliases.add_argument(
        "--include-transfer",
        action="store_true",
        help="Also learn aliases from transfer-labeled rows (default skips transfer).",
    )

    benchmark_review = benchmark_subparsers.add_parser("review")
    benchmark_review.add_argument("--source-file", help="Filter by source name.")
    benchmark_review.add_argument("--unlabeled-only", action="store_true", help="Only review unlabeled rows.")
    benchmark_review.add_argument("--start-id", type=int, help="Start from benchmark row id (inclusive).")
    benchmark_review.add_argument("--limit", type=int, help="Maximum rows to load for this session.")

    args = parser.parse_args()

    # Commands that do not require database connectivity.
    if args.command == "pdf-debug":
        await pdf_debug_command(args)
        return

    await init_db()

    if not args.command:
        # Launch Interactive Mode if no args
        await interactive_main()
    elif args.command == "account":
        await account_command(args)
    elif args.command == "convert":
        await convert_command(args)
    elif args.command == "keyword-debug":
        await keyword_debug_command(args)
    elif args.command == "keyword-backfill":
        await keyword_backfill_command(args)
    elif args.command == "category-debug":
        await category_debug_command(args)
    elif args.command == "llm":
        await llm_command(args)
    elif args.command == "db":
        await db_command(args)
    elif args.command == "queue":
        await queue_command(args)
    elif args.command == "add-tx":
        await add_tx_command(args)
    elif args.command == "benchmark":
        await benchmark_command(args)
    else:
        parser.print_help()


async def _run_main():
    try:
        await main()
    finally:
        await close_ollama_client()

if __name__ == "__main__":
    asyncio.run(_run_main())
