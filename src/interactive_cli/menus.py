import os
from datetime import datetime

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from sqlalchemy import func, select

from src.commands import (
    add_account,
    add_category,
    delete_account,
    delete_category,
    delete_global_memory_instruction,
    delete_transaction,
    export_to_bluecoins_csv,
    format_category_label,
    format_category_obj_label,
    get_all_accounts,
    get_all_categories,
    get_global_memory_entries,
    get_queue_transactions,
    get_resettable_table_names,
    get_table_row_counts,
    get_transaction_category_display,
    get_transactions,
    list_accounts,
    mark_transaction_verified,
    reset_database,
    reset_selected_tables,
    seed_reference_data,
    set_global_memory_active,
    update_account,
    update_transaction_category,
    update_transaction_note,
)
from src.database import Account, Transaction

from .common import TRANSFER_CHOICE, choose_category_tree
from .ui import (
    _Ansi,
    _confirm_destructive,
    _err,
    _info,
    _menu_help_panel,
    _ok,
    _paged_table_view,
    _render_menu_view,
    _select_with_search,
    _style,
    _toast,
    _warn,
)


async def manage_accounts_menu(session):
    while True:
        account_count = int(await session.scalar(select(func.count(Account.id))) or 0)
        pending_tx = int(
            await session.scalar(select(func.count(Transaction.id)).where(Transaction.is_verified.is_(False))) or 0
        )
        _render_menu_view(
            path="Home / Accounts",
            summary_lines=[
                f"Configured accounts: {account_count}",
                "Create, rename, or remove account sources.",
            ],
            pending=pending_tx,
        )
        action = await inquirer.select(
            message="Open Folder:",
            long_instruction=_menu_help_panel(
                [
                    "List Accounts: Quick inventory of available accounts.",
                    "Add Account: Register a new source statement account.",
                    "Edit Account: Rename account and cascade to linked transactions.",
                    "Delete Account: Remove account after confirmation.",
                ]
            ),
            choices=[
                "List Accounts",
                "Add Account",
                "Edit Account",
                "Delete Account",
                Choice(value=None, name="Back to Main Menu"),
            ],
        ).execute_async()

        if not action:
            break

        if action == "List Accounts":
            accounts = await list_accounts(session)
            if not accounts:
                _warn("No accounts found.")
            else:
                rows = []
                for acc in sorted(accounts, key=lambda a: (a.name or "").lower()):
                    linked = int(
                        await session.scalar(
                            select(func.count(Transaction.id)).where(Transaction.account_id == acc.id)
                        )
                        or 0
                    )
                    rows.append((acc.name, acc.institution, str(linked)))
                await _paged_table_view(
                    path="Home / Accounts / List",
                    title="Accounts",
                    headers=["Name", "Institution", "Linked Tx"],
                    rows=rows,
                    sort_options=[
                        ("name", lambda r: (r[0] or "").lower()),
                        ("institution", lambda r: (r[1] or "").lower()),
                        ("linked_tx", lambda r: int(r[2] or 0)),
                    ],
                )

        elif action == "Add Account":
            name = await inquirer.text(message="Account Name:").execute_async()
            inst = await inquirer.text(message="Institution (e.g. HSBC):").execute_async()
            success, msg = await add_account(session, name, inst)
            await _toast(msg, level="ok" if success else "err")

        elif action == "Delete Account":
            accounts = await list_accounts(session)
            if not accounts:
                _warn("No accounts to delete.")
                continue

            choices = [Choice(value=acc.name, name=acc.name) for acc in accounts]
            choices.append(Choice(value=None, name="Cancel"))

            target = await _select_with_search(
                message="Select Account to Delete:",
                choices=choices,
                threshold=8,
            )

            if target:
                ok_delete = await _confirm_destructive(
                    path="Home / Accounts / Delete",
                    action_label=f"delete account '{target}'",
                    typed_token="DELETE",
                )
                if ok_delete:
                    success, msg = await delete_account(session, target)
                    await _toast(msg, level="ok" if success else "err")

        elif action == "Edit Account":
            accounts = await list_accounts(session)
            if not accounts:
                _warn("No accounts to edit.")
                continue

            choices = [Choice(value=acc.name, name=f"{acc.name} ({acc.institution})") for acc in accounts]
            choices.append(Choice(value=None, name="Cancel"))
            current_name = await _select_with_search(
                message="Select Account to Edit:",
                choices=choices,
                threshold=8,
            )
            if not current_name:
                continue

            acc_res = await session.execute(select(Account).where(Account.name == current_name))
            account = acc_res.scalar_one_or_none()
            if not account:
                _err("Account not found.")
                continue

            new_name = await inquirer.text(message="New account name:", default=account.name).execute_async()
            if not (new_name or "").strip():
                _warn("Account name cannot be empty.")
                continue

            linked_tx_count = await session.scalar(
                select(func.count(Transaction.id)).where(Transaction.account_id == account.id)
            )
            linked_tx_count = int(linked_tx_count or 0)

            confirm = await inquirer.confirm(
                message=(
                    f"Rename '{account.name}' to '{new_name.strip()}' and update "
                    f"{linked_tx_count} linked transaction(s)?"
                )
            ).execute_async()
            if not confirm:
                _info("Edit canceled.")
                continue

            success, msg, updated_count = await update_account(
                session,
                current_name=account.name,
                new_name=new_name.strip(),
                new_institution=account.institution,
            )
            if success:
                await _toast(f"{msg} Updated {updated_count} linked transaction(s).", level="ok")
            else:
                await _toast(msg, level="err")


async def manage_transactions_menu(session):
    while True:
        total_tx = int(await session.scalar(select(func.count(Transaction.id))) or 0)
        pending_tx = int(
            await session.scalar(select(func.count(Transaction.id)).where(Transaction.is_verified.is_(False))) or 0
        )
        _render_menu_view(
            path="Home / Transactions",
            summary_lines=[
                f"Total transactions: {total_tx}",
                f"Pending verification: {pending_tx}",
            ],
            pending=pending_tx,
        )
        action = await inquirer.select(
            message="Open Folder:",
            long_instruction=_menu_help_panel(
                [
                    "View / Edit Recent: Inspect recent rows and manually adjust.",
                    "Review Queue: Process needs_review and force_review decisions.",
                    "Export to CSV: Export filtered transactions for Bluecoins import.",
                ]
            ),
            choices=[
                "View / Edit Recent Transactions",
                "Review Queue",
                "Export to CSV",
                Choice(value=None, name="Back to Main Menu"),
            ],
        ).execute_async()

        if not action:
            break

        accounts = await get_all_accounts(session)
        acc_choices = [Choice(value=acc.id, name=acc.name) for acc in accounts]
        acc_choices.insert(0, Choice(value=None, name="All Accounts"))

        account_id = await _select_with_search(
            message="Filter by Account:",
            choices=acc_choices,
            threshold=8,
        )

        if action == "Export to CSV":
            start_str = await inquirer.text(message="Start Date (YYYY-MM-DD) or Enter for All:").execute_async()
            start_date = datetime.strptime(start_str, "%Y-%m-%d") if start_str else None

            output_path = await inquirer.filepath(
                message="Output Path:",
                default="export.csv",
                validate=lambda x: not x or not os.path.isdir(x),
            ).execute_async()

            txs = await get_transactions(session, account_id=account_id, start_date=start_date)
            if not txs:
                _warn("No transactions found.")
                continue

            success, msg = export_to_bluecoins_csv(txs, output_path)
            await _toast(msg, level="ok" if success else "err")
        elif action == "Review Queue":
            await review_queue_menu(session, account_id=account_id)

        elif action == "View / Edit Recent Transactions":
            txs = await get_transactions(session, account_id=account_id)
            if not txs:
                _warn("No transactions found.")
                continue

            tx_rows = []
            for t in txs:
                parent_name, cat_name = get_transaction_category_display(t)
                cat_type = t.category.type if t.category else t.type
                tx_rows.append(
                    (
                        str(t.id),
                        t.date.strftime("%Y-%m-%d"),
                        t.type or "",
                        f"{t.amount:.2f}",
                        "Y" if t.is_verified else "N",
                        format_category_label(parent_name, cat_name, cat_type),
                        t.description or "",
                    )
                )
            await _paged_table_view(
                path="Home / Transactions / Recent",
                title="Recent Transactions",
                headers=["ID", "Date", "Type", "Amount", "V", "Category", "Description"],
                rows=tx_rows,
                sort_options=[
                    ("date", lambda r: r[1]),
                    ("amount", lambda r: float(r[3] or 0.0)),
                    ("type", lambda r: (r[2] or "").lower()),
                    ("verified", lambda r: (r[4] or "").lower()),
                ],
            )

            choices = []
            for t in txs[:50]:
                status = "✅" if t.is_verified else "  "
                parent_name, cat_name = get_transaction_category_display(t)
                cat_type = t.category.type if t.category else t.type
                cat_name = format_category_label(parent_name, cat_name, cat_type)
                label = (
                    f"{status} {t.date.strftime('%Y-%m-%d')} | {t.description[:20]:<20} | "
                    f"{t.amount:>8.2f} | {cat_name}"
                )
                choices.append(Choice(value=t, name=label))
            choices.append(Choice(value=None, name="Back"))

            selected_tx = await _select_with_search(
                message="Select Transaction to Edit:",
                choices=choices,
                threshold=15,
            )

            if not selected_tx:
                continue

            tx_action = await inquirer.select(
                message=f"Action for '{selected_tx.description}':",
                choices=[
                    "Change Category",
                    "Edit Note",
                    "Verify / Approve",
                    "Delete Transaction",
                    Choice(value=None, name="Cancel"),
                ],
            ).execute_async()

            if tx_action == "Change Category":
                selected_cat = await choose_category_tree(
                    session,
                    prompt_prefix="Select New Category",
                    default_type=selected_tx.type if selected_tx.type in {"income", "expense"} else None,
                    restrict_to_default_type=True,
                )
                if selected_cat == TRANSFER_CHOICE:
                    await update_transaction_category(session, selected_tx.id, category_id=None, set_transfer=True)
                    await _toast("Transaction updated.", level="ok")
                elif selected_cat:
                    await update_transaction_category(session, selected_tx.id, selected_cat.id)
                    await _toast("Transaction updated.", level="ok")

            elif tx_action == "Edit Note":
                new_note = await inquirer.text(
                    message="Transaction note (used as export Item/Payee when present):",
                    default=selected_tx.note or "",
                ).execute_async()
                success, msg = await update_transaction_note(session, selected_tx.id, new_note)
                await _toast(msg, level="ok" if success else "err")

            elif tx_action == "Verify / Approve":
                await mark_transaction_verified(session, selected_tx.id)
                await _toast("Transaction verified.", level="ok")

            elif tx_action == "Delete Transaction":
                ok_delete = await _confirm_destructive(
                    path="Home / Transactions / Delete",
                    action_label=f"delete transaction #{selected_tx.id}",
                    typed_token="DELETE",
                    details=[selected_tx.description or ""],
                )
                if ok_delete:
                    await delete_transaction(session, selected_tx.id)
                    await _toast("Transaction deleted.", level="ok")


async def review_queue_menu(session, account_id=None):
    while True:
        rows = await get_queue_transactions(session, account_id=account_id, limit=200)
        if not rows:
            _warn("No transactions pending review in queue.")
            return

        choices = []
        for tx in rows:
            parent_name, cat_name = get_transaction_category_display(tx)
            cat_type = tx.category.type if tx.category else tx.type
            cat_name = format_category_label(parent_name, cat_name, cat_type)
            label = (
                f"[{tx.decision_state}/{tx.review_bucket}] p{tx.review_priority or 0} "
                f"{tx.date.strftime('%Y-%m-%d')} | {tx.description[:24]:<24} | {tx.amount:>8.2f} | {cat_name}"
            )
            choices.append(Choice(value=tx, name=label))
        choices.append(Choice(value=None, name="Back"))

        _render_menu_view(
            path="Home / Transactions / Review Queue",
            summary_lines=[
                f"Rows in queue: {len(rows)}",
                "Focus on needs_review and force_review transactions.",
            ],
            pending=len(rows),
        )
        selected_tx = await _select_with_search(
            message="Select Transaction:",
            long_instruction=_menu_help_panel(
                [
                    "Accept & Verify: Confirms category/type and exits queue status.",
                    "Change Category: Manually set category and verify transaction.",
                    "Delete Transaction: Remove row from transaction history.",
                ]
            ),
            choices=choices,
            threshold=18,
        )
        if not selected_tx:
            return

        tx_action = await inquirer.select(
            message=f"Queue action for '{selected_tx.description}':",
            choices=[
                "Accept & Verify",
                "Change Category",
                "Edit Note",
                "Delete Transaction",
                Choice(value=None, name="Cancel"),
            ],
        ).execute_async()

        if tx_action == "Accept & Verify":
            await mark_transaction_verified(session, selected_tx.id)
            await _toast("Transaction verified.", level="ok")
            continue

        if tx_action == "Change Category":
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix="Queue: Select New Category",
                default_type=selected_tx.type if selected_tx.type in {"income", "expense"} else None,
                restrict_to_default_type=True,
            )
            if selected_cat == TRANSFER_CHOICE:
                await update_transaction_category(session, selected_tx.id, category_id=None, set_transfer=True)
                await _toast("Category updated and verified.", level="ok")
            elif selected_cat:
                await update_transaction_category(session, selected_tx.id, selected_cat.id)
                await _toast("Category updated and verified.", level="ok")
            continue

        if tx_action == "Edit Note":
            new_note = await inquirer.text(
                message="Transaction note (used as export Item/Payee when present):",
                default=selected_tx.note or "",
            ).execute_async()
            success, msg = await update_transaction_note(session, selected_tx.id, new_note)
            await _toast(msg, level="ok" if success else "err")
            continue

        if tx_action == "Delete Transaction":
            ok_delete = await _confirm_destructive(
                path="Home / Transactions / Review Queue / Delete",
                action_label=f"delete transaction #{selected_tx.id}",
                typed_token="DELETE",
                details=[selected_tx.description or ""],
            )
            if ok_delete:
                await delete_transaction(session, selected_tx.id)
                await _toast("Transaction deleted.", level="ok")
            continue


async def manage_categories_menu(session):
    while True:
        cats = await get_all_categories(session)
        pending_tx = int(
            await session.scalar(select(func.count(Transaction.id)).where(Transaction.is_verified.is_(False))) or 0
        )
        _render_menu_view(
            path="Home / Categories",
            summary_lines=[
                f"Configured categories: {len(cats)}",
                "Maintain parent groups and sub-category mappings.",
            ],
            pending=pending_tx,
        )
        action = await inquirer.select(
            message="Open Folder:",
            long_instruction=_menu_help_panel(
                [
                    "List Categories: Print category tree grouped by type and parent.",
                    "Add Category: Create new category under a parent group.",
                    "Delete Category: Remove category with optional reassignment.",
                ]
            ),
            choices=[
                "List Categories",
                "Add Category",
                "Delete Category",
                Choice(value=None, name="Back to Main Menu"),
            ],
        ).execute_async()

        if not action:
            break

        if action == "List Categories":
            cats = await get_all_categories(session)
            if not cats:
                _warn("No categories found.")
                continue

            rows = [
                (
                    str(c.id),
                    (c.type or "unknown"),
                    (c.parent_name or "Uncategorized"),
                    (c.name or ""),
                )
                for c in cats
            ]
            await _paged_table_view(
                path="Home / Categories / List",
                title="Categories",
                headers=["ID", "Type", "Parent", "Category"],
                rows=rows,
                sort_options=[
                    ("id", lambda r: int(r[0] or 0)),
                    ("type", lambda r: (r[1] or "").lower()),
                    ("parent", lambda r: (r[2] or "").lower()),
                    ("category", lambda r: (r[3] or "").lower()),
                ],
            )

        elif action == "Add Category":
            cat_type = await inquirer.select(message="Category Type:", choices=["expense", "income"]).execute_async()

            is_new_parent = await inquirer.confirm(message="Is this a new Parent Category Group?").execute_async()

            parent_name = ""
            if is_new_parent:
                parent_name = await inquirer.text(message="Enter New Parent Group Name:").execute_async()
            else:
                cats = await get_all_categories(session)
                parents = sorted(list(set(c.parent_name for c in cats if c.type == cat_type)))
                if not parents:
                    _warn(f"No existing {cat_type} parent categories. You must create one.")
                    parent_name = await inquirer.text(message="Enter New Parent Group Name:").execute_async()
                else:
                    parent_name = await inquirer.fuzzy(
                        message="Select Parent Group:",
                        choices=[f"{p} [{cat_type}]" for p in parents],
                    ).execute_async()
                    if parent_name:
                        parent_name = parent_name.rsplit(" [", 1)[0]

            if not parent_name:
                continue

            name = await inquirer.text(message="Enter Category Name:").execute_async()
            if not name:
                continue

            success, msg = await add_category(session, name, parent_name, cat_type)
            await _toast(msg, level="ok" if success else "err")

        elif action == "Delete Category":
            cats = await get_all_categories(session)
            if not cats:
                _warn("No categories to delete.")
                continue

            choices = [Choice(value=c, name=format_category_obj_label(c)) for c in cats]
            choices.append(Choice(value=None, name="Cancel"))

            target_cat = await _select_with_search(
                message="Select Category to Delete:",
                choices=choices,
                threshold=12,
            )

            if not target_cat:
                continue

            stmt = select(Transaction).where(Transaction.category_id == target_cat.id)
            res = await session.execute(stmt)
            txs = res.scalars().all()
            count = len(txs)

            reassign_id = None
            delete_txs = False

            if count > 0:
                _warn(f"\nWarning: This category has {count} transactions assigned to it.")
                sub_action = await inquirer.select(
                    message="How to handle these transactions?",
                    choices=[
                        Choice(value="reassign", name="Re-assign to another category"),
                        Choice(value="delete", name="Delete transactions too"),
                        Choice(value="cancel", name="Cancel Operation"),
                    ],
                ).execute_async()

                if sub_action == "cancel":
                    continue

                if sub_action == "delete":
                    confirm_del = await inquirer.confirm(
                        message=f"Are you sure you want to delete {count} transactions?"
                    ).execute_async()
                    if not confirm_del:
                        continue
                    delete_txs = True

                elif sub_action == "reassign":
                    other_cats = [c for c in cats if c.id != target_cat.id]
                    if not other_cats:
                        _warn("No other categories to reassign to!")
                        continue

                    rc_choices = [Choice(value=c.id, name=format_category_obj_label(c)) for c in other_cats]
                    reassign_id = await _select_with_search(
                        message="Select New Category for transactions:",
                        choices=rc_choices,
                        threshold=12,
                    )

                    if not reassign_id:
                        continue

            ok_delete = await _confirm_destructive(
                path="Home / Categories / Delete",
                action_label=f"delete category '{format_category_obj_label(target_cat)}'",
                typed_token="DELETE",
                details=[f"assigned_transactions={count}"],
            )
            if ok_delete:
                success, msg = await delete_category(
                    session,
                    target_cat.id,
                    reassign_category_id=reassign_id,
                    delete_transactions=delete_txs,
                )
                await _toast(msg, level="ok" if success else "err")


async def manage_global_rulebook_menu(session):
    while True:
        active_rules = len(await get_global_memory_entries(session, include_inactive=False, limit=500))
        pending_tx = int(
            await session.scalar(select(func.count(Transaction.id)).where(Transaction.is_verified.is_(False))) or 0
        )
        _render_menu_view(
            path="Home / AI Rulebook",
            summary_lines=[
                f"Active global rules: {active_rules}",
                "Persist coaching instructions used by categorization flows.",
            ],
            pending=pending_tx,
        )
        action = await inquirer.select(
            message="Open Folder:",
            long_instruction=_menu_help_panel(
                [
                    "List Rules: Show active/inactive global memory instructions.",
                    "Add Rule: Persist a new high-level categorization rule.",
                    "Enable/Disable: Toggle rule applicability.",
                    "Delete Rule: Permanently remove a rule.",
                ]
            ),
            choices=[
                "List Rules",
                "Add Rule",
                "Disable Rule",
                "Enable Rule",
                "Delete Rule",
                Choice(value=None, name="Back to Main Menu"),
            ],
        ).execute_async()

        if not action:
            break

        if action == "List Rules":
            rules = await get_global_memory_entries(session, include_inactive=True, limit=500)
            if not rules:
                _warn("No global rules found.")
                continue
            rows = []
            for r in rules:
                status = "ACTIVE" if r.is_active else "INACTIVE"
                created = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"
                rows.append((str(r.id), status, created, r.source or "", r.instruction or ""))
            await _paged_table_view(
                path="Home / AI Rulebook / List",
                title="Global Rules",
                headers=["ID", "Status", "Created", "Source", "Instruction"],
                rows=rows,
                sort_options=[
                    ("id", lambda r: int(r[0] or 0)),
                    ("status", lambda r: (r[1] or "").lower()),
                    ("created", lambda r: r[2]),
                    ("source", lambda r: (r[3] or "").lower()),
                ],
            )

        elif action == "Add Rule":
            text = await inquirer.text(message="Rule text to persist:").execute_async()
            ok, msg = await add_global_memory_instruction(session, text, source="manual_rulebook")
            await session.commit()
            await _toast(msg, level="ok" if ok else "err")

        elif action in {"Disable Rule", "Enable Rule"}:
            target_active = action == "Enable Rule"
            rules = await get_global_memory_entries(session, include_inactive=True, limit=500)
            if not rules:
                _warn("No rules available.")
                continue
            filtered = [r for r in rules if r.is_active != target_active]
            if not filtered:
                state_name = "inactive" if target_active else "active"
                _warn(f"No {state_name} rules found to modify.")
                continue

            choices = [Choice(value=r.id, name=f"#{r.id} [{r.source}] {r.instruction[:90]}") for r in filtered]
            choices.append(Choice(value=None, name="Cancel"))
            selected_id = await _select_with_search(
                message=f"Select rule to {'enable' if target_active else 'disable'}:",
                choices=choices,
                threshold=12,
            )
            if selected_id:
                ok, msg = await set_global_memory_active(session, selected_id, target_active)
                await _toast(msg, level="ok" if ok else "err")

        elif action == "Delete Rule":
            rules = await get_global_memory_entries(session, include_inactive=True, limit=500)
            if not rules:
                _warn("No rules available.")
                continue
            choices = [
                Choice(
                    value=r.id,
                    name=f"#{r.id} [{'ACTIVE' if r.is_active else 'INACTIVE'}] {r.instruction[:90]}",
                )
                for r in rules
            ]
            choices.append(Choice(value=None, name="Cancel"))
            selected_id = await _select_with_search(
                message="Select rule to delete:",
                choices=choices,
                threshold=12,
            )
            if selected_id:
                ok_delete = await _confirm_destructive(
                    path="Home / AI Rulebook / Delete",
                    action_label=f"delete rule #{selected_id}",
                    typed_token="DELETE",
                )
                if ok_delete:
                    ok, msg = await delete_global_memory_instruction(session, selected_id)
                    await _toast(msg, level="ok" if ok else "err")


async def reset_database_menu(session):
    pending_tx = int(
        await session.scalar(select(func.count(Transaction.id)).where(Transaction.is_verified.is_(False))) or 0
    )
    _render_menu_view(
        path="Home / Reset",
        summary_lines=[
            "Danger Zone: reset operations are destructive.",
            "Use table-level reset unless a full reset is required.",
        ],
        pending=pending_tx,
    )
    action = await inquirer.select(
        message="Reset Options:",
        long_instruction=_menu_help_panel(
            [
                "Reset Entire Database: Wipes and reseeds baseline data.",
                "Reset Specific Tables: Safer targeted reset for selected tables.",
                "Type RESET when prompted for irreversible operations.",
            ]
        ),
        choices=[
            "Reset Entire Database",
            "Reset Specific Tables",
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()

    if not action:
        return

    if action == "Reset Entire Database":
        ok_confirm = await _confirm_destructive(
            path="Home / Reset / Entire Database",
            action_label="reset entire database",
            typed_token="RESET",
            details=["This will wipe all resettable tables and reseed reference data."],
        )
        if not ok_confirm:
            return

        ok, msg = await reset_database()
        await _toast(msg, level="ok" if ok else "err")
        _ok_seed, seed_msg = await seed_reference_data(session)
        await _toast(seed_msg, level="info")
        return

    table_names = get_resettable_table_names()
    counts = await get_table_row_counts(session, table_names=table_names)
    table_choices = [Choice(value=t, name=f"{t} ({counts.get(t, 0)} rows)") for t in table_names]
    selected = await inquirer.checkbox(message="Select tables to reset:", choices=table_choices).execute_async()

    if not selected:
        _warn("No tables selected.\n")
        return

    ok_confirm = await _confirm_destructive(
        path="Home / Reset / Selected Tables",
        action_label=f"reset selected tables ({', '.join(selected)})",
        typed_token="RESET",
    )
    if not ok_confirm:
        return

    ok, msg = await reset_selected_tables(session, selected)
    if ok:
        await _toast(msg, level="ok")
    else:
        await _toast(msg, level="err")
