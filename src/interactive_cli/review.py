import textwrap

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.ai import CategorizerAI
from src.commands import (
    add_global_memory_instruction,
    delete_transaction,
    format_category_label,
    format_category_obj_label,
    get_category_display_from_values,
    mark_transaction_verified,
    update_transaction_category,
)
from src.database import AIMemory, Transaction
from src.patterns import extract_pattern_key_result
from src.tui import TransactionReviewApp

from .common import TRANSFER_CHOICE, choose_category_tree


async def _get_or_create_latest_memory_entry(session, tx):
    mem_stmt = (
        select(AIMemory)
        .where(AIMemory.transaction_id == tx.id)
        .order_by(AIMemory.created_at.desc())
        .limit(1)
    )
    mem_res = await session.execute(mem_stmt)
    memory = mem_res.scalars().first()
    if memory:
        return memory

    memory = AIMemory(
        transaction_id=tx.id,
        pattern_key=extract_pattern_key_result(tx.description).keyword,
        ai_suggested_category_id=tx.category_id,
        user_selected_category_id=tx.category_id,
        ai_reasoning=tx.decision_reason or "",
    )
    session.add(memory)
    await session.flush()
    return memory


def _tx_data_from_row(tx):
    return {
        "id": tx.id,
        "date": tx.date.strftime("%Y-%m-%d") if tx.date else "",
        "amount": tx.amount,
        "description": tx.description or "",
        "type": tx.type,
        "raw_csv_row": tx.raw_csv_row or "",
    }


async def _category_label_for_tx(session, tx_type, category_id):
    parent_name, cat_name = await get_category_display_from_values(session, tx_type, category_id)
    return format_category_label(parent_name, cat_name, tx_type)


async def review_transactions(session, transactions):
    tx_ids = [t.id for t in transactions]
    if not tx_ids:
        return

    stmt = select(Transaction).options(
        selectinload(Transaction.category),
        selectinload(Transaction.account),
        selectinload(Transaction.memory_entries),
    ).where(Transaction.id.in_(tx_ids)).order_by(Transaction.date.desc())

    res = await session.execute(stmt)
    review_list = res.scalars().all()

    if not review_list:
        print("No transactions to review.")
        return

    ai = CategorizerAI()

    async def on_update(tx, action):
        if action == "verify":
            await mark_transaction_verified(session, tx.id)

    while True:
        app = TransactionReviewApp(review_list, session, update_callback=on_update)
        result = await app.run_async()

        if result is None:
            break

        action, tx = result

        if action == "modify":
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix=f"'{tx.description}'",
                default_type=tx.type if tx.type in {"income", "expense"} else None,
                restrict_to_default_type=True,
            )
            if selected_cat == TRANSFER_CHOICE:
                await update_transaction_category(session, tx.id, category_id=None, set_transfer=True)
                await session.refresh(tx, ["category", "memory_entries"])
            elif selected_cat:
                await update_transaction_category(session, tx.id, selected_cat.id)
                await session.refresh(tx, ["category", "memory_entries"])
            else:
                continue

            follow_up = await inquirer.select(
                message="Post-change learning:",
                choices=[
                    Choice(value="coach", name="Coach model with explicit rule"),
                    Choice(value="discuss", name="Discuss and synthesize guidance"),
                    Choice(value="none", name="Done"),
                ],
                default="coach",
            ).execute_async()
            action = follow_up

        if action == "coach":
            coaching_text = await inquirer.text(
                message="Coaching instruction to save in global rulebook:"
            ).execute_async()
            coaching_text = (coaching_text or "").strip()
            if not coaching_text:
                continue

            await add_global_memory_instruction(session, coaching_text, source="review_coaching")
            await session.commit()
            print("Saved coaching rule.")

            rerun = await inquirer.confirm(
                message="Re-run AI suggestion for this transaction using this coaching?",
                default=True,
            ).execute_async()
            if rerun:
                locked_expected_type = tx.type if tx.type in {"expense", "income"} else None
                candidates = await ai.suggest_category_candidates(
                    tx.description,
                    session,
                    min_candidates=3,
                    extra_instruction=coaching_text,
                    expected_type=locked_expected_type,
                )
                if candidates:
                    top = candidates[0]
                    suggested_label = await _category_label_for_tx(session, top["type"], top["id"])
                    apply_top = await inquirer.confirm(
                        message=f"Apply top coached suggestion now? {suggested_label}",
                        default=False,
                    ).execute_async()
                    if apply_top:
                        await update_transaction_category(session, tx.id, top["id"])
                        await session.refresh(tx, ["category", "memory_entries"])
                        print("Applied coached suggestion.")
            continue

        if action == "discuss":
            print("\nDiscussion mode. Use /done to finish and /search <query> to force web lookup.")
            discussion_history = []
            tx_data = _tx_data_from_row(tx)

            while True:
                user_msg = await inquirer.text(message="You:").execute_async()
                user_msg = (user_msg or "").strip()
                if not user_msg:
                    continue
                if user_msg.lower() in {"/done", "done", "exit"}:
                    break

                forced_search_query = None
                llm_message = user_msg
                if user_msg.lower().startswith("/search"):
                    forced_search_query = user_msg[7:].strip()
                    if not forced_search_query:
                        print("Usage: /search <query>")
                        continue
                    llm_message = (
                        "Use this explicit web search context to evaluate the current decision. "
                        f"Query: {forced_search_query}. Explain whether category/type should change and why."
                    )

                memory = await _get_or_create_latest_memory_entry(session, tx)
                reply = await ai.discuss_transaction(
                    tx_data=tx_data,
                    current_type=tx.type,
                    current_cat_id=tx.category_id,
                    current_reasoning=memory.ai_reasoning or tx.decision_reason or "No reasoning.",
                    session=session,
                    user_message=llm_message,
                    conversation_history=discussion_history,
                    web_search_query=forced_search_query,
                )
                discussion_history.append({"role": "user", "content": user_msg})
                discussion_history.append({"role": "assistant", "content": reply})
                print(f"\nModel: {reply}\n")

            if discussion_history:
                guidance = await ai.summarize_review_conversation(
                    tx_description=tx.description,
                    conversation_history=discussion_history,
                )
                if guidance and guidance.strip():
                    guidance_text = guidance.strip()
                    print("\nSynthesized guidance:\n" + guidance + "\n")
                    persist = await inquirer.confirm(
                        message="Save this guidance in global rulebook?",
                        default=True,
                    ).execute_async()
                    if persist:
                        await add_global_memory_instruction(
                            session,
                            guidance_text,
                            source="review_discussion",
                        )
                        await session.commit()
                        print("Saved guidance rule.")

                    rerun = await inquirer.confirm(
                        message="Re-run AI suggestion for this transaction using this guidance?",
                        default=True,
                    ).execute_async()
                    if rerun:
                        locked_expected_type = tx.type if tx.type in {"expense", "income"} else None
                        candidates = await ai.suggest_category_candidates(
                            tx.description,
                            session,
                            min_candidates=3,
                            extra_instruction=guidance_text,
                            expected_type=locked_expected_type,
                        )
                        if candidates:
                            top = candidates[0]
                            suggested_label = await _category_label_for_tx(session, top["type"], top["id"])
                            apply_top = await inquirer.confirm(
                                message=f"Apply top discussion suggestion now? {suggested_label}",
                                default=False,
                            ).execute_async()
                            if apply_top:
                                await update_transaction_category(session, tx.id, top["id"])
                                await session.refresh(tx, ["category", "memory_entries"])
                                print("Applied discussion suggestion.")
            continue

        if action == "reflect":
            current_label = await _category_label_for_tx(session, tx.type, tx.category_id)
            memory = await _get_or_create_latest_memory_entry(session, tx)
            prior_reasoning = memory.ai_reasoning or tx.decision_reason or "No prior reasoning."
            reflection = await ai.generate_correctness_reflection(
                tx.description,
                current_label,
                prior_reasoning,
            )
            memory.user_selected_category_id = tx.category_id
            memory.reflection = reflection
            session.add(memory)
            await session.commit()
            print(f"Saved reflection: {reflection}")

            if not tx.is_verified:
                verify_now = await inquirer.confirm(
                    message="Mark this transaction as verified now?",
                    default=True,
                ).execute_async()
                if verify_now:
                    await mark_transaction_verified(session, tx.id)
                    await session.refresh(tx, ["memory_entries"])
            continue

        if action == "delete":
            confirm = await inquirer.confirm(message=f"Delete '{tx.description}'?").execute_async()
            if confirm:
                await delete_transaction(session, tx.id)
                review_list.remove(tx)
                if not review_list:
                    print("All transactions deleted.")
                    break


async def import_review_callback(tx_data, current_cat_id, confidence, current_type, reasoning, session):
    def box_text(lines, width=88):
        out = []
        border = "+" + "-" * (width - 2) + "+"
        out.append(border)
        for line in lines:
            wrapped = textwrap.wrap(str(line), width=width - 4) or [""]
            for part in wrapped:
                out.append(f"| {part:<{width - 4}} |")
        out.append(border)
        return "\n".join(out)

    def source_block_lines(raw_csv_row):
        raw = (raw_csv_row or "").strip()
        if not raw:
            return []
        if " | " in raw:
            return [x.strip() for x in raw.split(" | ") if x.strip()]
        return [raw]

    ai = CategorizerAI()
    effective_cat_id = current_cat_id
    effective_type = current_type
    effective_confidence = confidence
    effective_reasoning = reasoning
    change_log = []
    discussion_history = []
    locked_expected_type = tx_data["type"] if tx_data.get("type") in {"expense", "income"} else None
    suggestion_candidates = await ai.suggest_category_candidates(
        tx_data["description"],
        session,
        min_candidates=3,
        expected_type=locked_expected_type,
    )

    while True:
        if effective_type == "transfer":
            effective_cat_id = None

        parent_name, cat_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
        suggestion_label = format_category_label(parent_name, cat_name, effective_type)

        type_disp = effective_type.upper()
        if effective_type == "transfer":
            type_disp = "TRANSFER OUT" if tx_data["amount"] < 0 else "TRANSFER IN"

        suggestion_lines = []
        for idx, candidate in enumerate(suggestion_candidates[:5], start=1):
            s_parent, s_name = await get_category_display_from_values(session, candidate["type"], candidate["id"])
            s_label = format_category_label(s_parent, s_name, candidate["type"])
            suggestion_lines.append(f"  {idx}. {s_label} ({candidate['confidence']:.2f})")
        if not suggestion_lines:
            suggestion_lines = ["  No category suggestions available."]

        block_lines = source_block_lines(tx_data.get("raw_csv_row"))
        block_section = []
        if block_lines:
            block_section.extend(["Source Block:"])
            block_section.extend([f"  - {line}" for line in block_lines])

        summary_box = box_text([
            f"Date: {tx_data['date']}    Amount: {tx_data['amount']}",
            f"Type: {type_disp}",
            f"Description: {tx_data['description']}",
            *block_section,
            f"AI Suggestion: {suggestion_label}",
            f"Confidence: {effective_confidence:.2f}",
            f"Reasoning: {effective_reasoning}",
            "Suggested Categories:",
            *suggestion_lines,
        ])

        action = await inquirer.select(
            message=f"{summary_box}\nAction:",
            choices=[
                Choice(value="accept", name="Accept & Verify"),
                Choice(value="pick_suggested", name="Pick from Suggested Categories"),
                Choice(value="change", name="Change Category"),
                Choice(value="refresh", name="Refresh LLM Reasoning"),
                Choice(value="coach", name="Coach Model"),
                Choice(value="discuss", name="Discuss Current Decision"),
                Choice(value="skip", name="Skip Review (Accept as AI prediction)"),
            ],
            default="accept",
        ).execute_async()

        if action == "accept":
            if change_log:
                change_summary = " | ".join(change_log)
                if effective_reasoning:
                    effective_reasoning = f"{effective_reasoning} [Review changes: {change_summary}]"
                else:
                    effective_reasoning = f"Review changes: {change_summary}"
            return effective_cat_id, True, effective_type, effective_confidence, effective_reasoning

        if action == "skip":
            if change_log:
                change_summary = " | ".join(change_log)
                if effective_reasoning:
                    effective_reasoning = f"{effective_reasoning} [Review changes: {change_summary}]"
                else:
                    effective_reasoning = f"Review changes: {change_summary}"
            return effective_cat_id, False, effective_type, effective_confidence, effective_reasoning

        if action == "pick_suggested":
            if not suggestion_candidates:
                print("No suggested categories available.")
                continue

            choices = []
            for idx, candidate in enumerate(suggestion_candidates[:10], start=1):
                s_parent, s_name = await get_category_display_from_values(session, candidate["type"], candidate["id"])
                s_label = format_category_label(s_parent, s_name, candidate["type"])
                choices.append(
                    Choice(
                        value=candidate,
                        name=f"{idx}. {s_label} | conf={candidate['confidence']:.2f}",
                    )
                )
            choices.append(Choice(value=None, name="Back"))

            selected = await inquirer.select(
                message="Select suggested category:",
                choices=choices,
            ).execute_async()
            if selected:
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = selected["id"]
                effective_type = selected["type"]
                effective_confidence = selected["confidence"]
                effective_reasoning = selected["reasoning"]
                new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                new_label = format_category_label(new_parent, new_name, effective_type)
                if old_label != new_label:
                    change_log.append(f"suggested pick {old_label} -> {new_label}")
            continue

        if action == "change":
            selected_cat = await choose_category_tree(
                session,
                prompt_prefix="Change Category",
                default_type=locked_expected_type or (effective_type if effective_type in {"income", "expense"} else None),
                restrict_to_default_type=bool(locked_expected_type),
            )
            if selected_cat == TRANSFER_CHOICE:
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = None
                effective_type = "transfer"
                new_label = "(Transfer) > (Transfer) [transfer]"
                prior_reasoning = effective_reasoning or "No prior reasoning."
                reflection = await ai.generate_reflection(
                    tx_data["description"],
                    old_label,
                    new_label,
                    prior_reasoning,
                )
                effective_reasoning = (
                    f"Manual override during review: changed from {old_label} to {new_label}. "
                    f"Reflection: {reflection}"
                )
                effective_confidence = 1.0
                if old_label != new_label:
                    change_log.append(f"manual override {old_label} -> {new_label}")
            elif selected_cat:
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                effective_cat_id = selected_cat.id
                effective_type = selected_cat.type
                new_label = format_category_obj_label(selected_cat)
                prior_reasoning = effective_reasoning or "No prior reasoning."
                reflection = await ai.generate_reflection(
                    tx_data["description"],
                    old_label,
                    new_label,
                    prior_reasoning,
                )
                effective_reasoning = (
                    f"Manual override during review: changed from {old_label} to {new_label}. "
                    f"Reflection: {reflection}"
                )
                effective_confidence = 1.0
                if old_label != new_label:
                    change_log.append(f"manual override {old_label} -> {new_label}")
            continue

        if action == "refresh":
            old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
            old_label = format_category_label(old_parent, old_name, effective_type)
            suggestion_candidates = await ai.suggest_category_candidates(
                tx_data["description"], session, min_candidates=3, expected_type=locked_expected_type
            )
            if suggestion_candidates:
                top = suggestion_candidates[0]
                effective_cat_id = top["id"]
                effective_confidence = top["confidence"]
                effective_reasoning = top["reasoning"]
                effective_type = top["type"] or effective_type
            new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
            new_label = format_category_label(new_parent, new_name, effective_type)
            if old_label != new_label:
                change_log.append(f"refresh changed suggestion {old_label} -> {new_label}")
            continue

        if action == "coach":
            coaching_text = await inquirer.text(
                message="Add coaching for model memory (global rulebook):"
            ).execute_async()
            if coaching_text and coaching_text.strip():
                await add_global_memory_instruction(session, coaching_text.strip(), source="review_coaching")
                suggestion_candidates = await ai.suggest_category_candidates(
                    tx_data["description"],
                    session,
                    min_candidates=3,
                    extra_instruction=coaching_text.strip(),
                    expected_type=locked_expected_type,
                )
                old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                old_label = format_category_label(old_parent, old_name, effective_type)
                if suggestion_candidates:
                    top = suggestion_candidates[0]
                    effective_cat_id = top["id"]
                    effective_confidence = top["confidence"]
                    effective_reasoning = top["reasoning"]
                    effective_type = top["type"] or effective_type
                new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                new_label = format_category_label(new_parent, new_name, effective_type)
                if old_label != new_label:
                    change_log.append(f"coached update {old_label} -> {new_label}")
            continue

        if action == "discuss":
            print("\nDiscussion mode for current transaction.")
            print("Commands: /done to return, /search <query> to force web search.\n")

            while True:
                user_msg = await inquirer.text(message="You:").execute_async()
                user_msg = (user_msg or "").strip()

                if not user_msg:
                    continue
                if user_msg.lower() in {"/done", "done", "exit"}:
                    break

                forced_search_query = None
                llm_message = user_msg

                if user_msg.lower().startswith("/search"):
                    forced_search_query = user_msg[7:].strip()
                    if not forced_search_query:
                        print("Usage: /search <query>")
                        continue
                    llm_message = (
                        "Use this explicit web search context to review the current decision. "
                        f"Query: {forced_search_query}. Explain whether category/type should change and why."
                    )

                model_reply = await ai.discuss_transaction(
                    tx_data=tx_data,
                    current_type=effective_type,
                    current_cat_id=effective_cat_id,
                    current_reasoning=effective_reasoning,
                    session=session,
                    user_message=llm_message,
                    conversation_history=discussion_history,
                    web_search_query=forced_search_query,
                )

                discussion_history.append({"role": "user", "content": user_msg})
                discussion_history.append({"role": "assistant", "content": model_reply})
                print("\n" + box_text([f"Model: {model_reply}"]))

            if discussion_history:
                conversation_instruction = await ai.summarize_review_conversation(
                    tx_description=tx_data["description"], conversation_history=discussion_history
                )
                if conversation_instruction and conversation_instruction.strip():
                    old_parent, old_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                    old_label = format_category_label(old_parent, old_name, effective_type)

                    suggestion_candidates = await ai.suggest_category_candidates(
                        tx_data["description"],
                        session,
                        min_candidates=3,
                        extra_instruction=conversation_instruction.strip(),
                        expected_type=locked_expected_type,
                    )
                    if suggestion_candidates:
                        top = suggestion_candidates[0]
                        effective_cat_id = top["id"]
                        effective_confidence = top["confidence"]
                        effective_reasoning = (
                            f"{top['reasoning']} [Conversation guidance applied: {conversation_instruction.strip()}]"
                        )
                        effective_type = top["type"] or effective_type

                    new_parent, new_name = await get_category_display_from_values(session, effective_type, effective_cat_id)
                    new_label = format_category_label(new_parent, new_name, effective_type)
                    if old_label != new_label:
                        change_log.append(f"discussion-informed update {old_label} -> {new_label}")
            continue
