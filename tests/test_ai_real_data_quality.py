import json
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.ai import CategorizerAI
from src.commands import (
    add_account,
    add_category,
    add_transaction,
    rebuild_category_understanding,
    update_transaction_category,
)
from src.database import (
    AICategoryUnderstanding,
    AIGlobalMemory,
    AIMemory,
    Account,
    Category,
    CategoryBenchmarkItem,
    Transaction,
)
from src.patterns import extract_pattern_key_result


REAL_FUEL_TX = (
    "UNITED ANKETELL NTH 10FEB26 ATMA896 21:39:21 4402   VISA    AUD "
    "UNITED ANKETELL NTH 331153 ANKETELL   AU A88879448 ATM"
)
REAL_GROCERY_TX = (
    "VISA DEBIT PURCHASE CARD 8208 WOOLWORTHS/ NICHOLSON RD & CANNINGVALE"
)
REAL_TRANSFER_OUT_TX = "PAYMENT TO S KARLAPUDI #044193"
REAL_TRANSFER_INTERNAL_TX = (
    "TRANSFER LP SDB60271Y ANZ Joint Account 665889369 "
    "Joint Bank Transfe YIB153034 INTERNET BANKING"
)
REAL_FOOD_TX = (
    "HUNGRY JACKS 05JAN26 ATMA896 20:06:11 4402   VISA    AUD "
    "Hungry Jacks 126058 Livingston  AU A88824047 ATM"
)


class StubCategorizer(CategorizerAI):
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.model = "test-model"
        self.client = None

    async def _chat_once(self, prompt):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("No stubbed response left for _chat_once")
        return self.responses.pop(0)

    def _run_web_search(self, query, max_results=3):
        return []


async def _seed_core_reference_data(session):
    account = Account(name=f"ANZ Main {uuid4().hex[:8]}", institution="ANZ")
    cats = [
        Category(name="Food", parent_name="Entertainment", type="expense"),
        Category(name="Fuel", parent_name="Transportation", type="expense"),
        Category(name="Shopping", parent_name="Entertainment", type="expense"),
        Category(name="Grocery", parent_name="Household", type="expense"),
        Category(name="Salary", parent_name="Employer", type="income"),
        Category(name="Transfer", parent_name="Others", type="expense"),
    ]
    session.add(account)
    session.add_all(cats)
    await session.flush()
    return account, {f"{c.parent_name}>{c.name}>{c.type}": c for c in cats}


def test_extract_pattern_key_real_transfer_payee():
    result = extract_pattern_key_result(REAL_TRANSFER_OUT_TX)
    assert "S KARLAPUDI" in result.keyword
    assert result.source == "rule"
    assert result.confidence >= 0.75


def test_extract_pattern_key_real_supermarket_slash_format():
    result = extract_pattern_key_result(REAL_GROCERY_TX)
    assert result.keyword == "WOOLWORTHS"
    assert result.source == "rule"
    assert result.confidence >= 0.75


def test_extract_pattern_key_real_internal_transfer_phrase():
    result = extract_pattern_key_result(REAL_TRANSFER_INTERNAL_TX)
    assert result.keyword.startswith("LP ANZ JOINT")
    assert result.source == "rule"
    assert result.confidence >= 0.55


@pytest.mark.asyncio
async def test_suggest_candidates_prompt_includes_memory_understanding_and_rules(db_session):
    account, cats = await _seed_core_reference_data(db_session)
    fuel = cats["Transportation>Fuel>expense"]
    food = cats["Entertainment>Food>expense"]
    shopping = cats["Entertainment>Shopping>expense"]

    tx = Transaction(
        date=datetime(2026, 2, 11),
        description=REAL_FUEL_TX,
        amount=63.02,
        type="expense",
        account_id=account.id,
        category_id=fuel.id,
        is_verified=True,
    )
    db_session.add(tx)
    await db_session.flush()
    db_session.add(
        AIMemory(
            transaction_id=tx.id,
            pattern_key="UNITED ANKETELL NTH",
            ai_suggested_category_id=fuel.id,
            user_selected_category_id=fuel.id,
            ai_reasoning="Fuel station merchant signal.",
            reflection="When merchant is UNITED, categorize as Fuel.",
        )
    )
    db_session.add(
        AICategoryUnderstanding(
            category_id=fuel.id,
            understanding="Fuel profile from verified United/ Ampol transactions.",
            sample_transactions_json=json.dumps({"samples": [REAL_FUEL_TX], "patterns": ["UNITED"]}),
        )
    )
    db_session.add(
        AIGlobalMemory(
            instruction="Never use suburb/location tail as merchant intent.",
            source="unit_test",
            is_active=True,
        )
    )
    await db_session.commit()

    payload = json.dumps(
        {
            "candidates": [
                {"id": fuel.id, "type": "expense", "confidence": 0.93, "reasoning": "United is fuel station."},
                {"id": food.id, "type": "expense", "confidence": 0.40, "reasoning": "Fallback food."},
                {"id": shopping.id, "type": "expense", "confidence": 0.30, "reasoning": "Fallback shopping."},
            ]
        }
    )
    ai = StubCategorizer([payload])
    similar_but_not_exact = (
        "UNITED ANKETELL NTH 11FEB26 ATMA896 09:39:21 4402 VISA AUD "
        "UNITED ANKETELL NTH 331153 ANKETELL AU A99999999 ATM"
    )

    candidates = await ai.suggest_category_candidates(similar_but_not_exact, db_session, expected_type="expense")
    assert candidates[0]["id"] == fuel.id
    assert len(candidates) >= 3

    prompt = ai.prompts[0]
    assert "LEARNING/REFLECTION" in prompt
    assert "Fuel profile from verified United/ Ampol transactions." in prompt
    assert "Never use suburb/location tail as merchant intent." in prompt
    assert "Global User Rulebook" in prompt


@pytest.mark.asyncio
async def test_suggest_candidates_repairs_and_filters_invalid_candidates_edge_cases(db_session):
    _, cats = await _seed_core_reference_data(db_session)
    food = cats["Entertainment>Food>expense"]
    fuel = cats["Transportation>Fuel>expense"]
    shopping = cats["Entertainment>Shopping>expense"]
    salary = cats["Employer>Salary>income"]

    repaired = json.dumps(
        {
            "candidates": [
                {"id": food.id, "type": "expense", "confidence": 0.90, "reasoning": "Hungry Jacks is food."},
                {"id": food.id, "type": "expense", "confidence": 0.89, "reasoning": "Duplicate should be removed."},
                {"id": salary.id, "type": "income", "confidence": 0.88, "reasoning": "Wrong type for expected expense."},
                {"id": 99999, "type": "expense", "confidence": 0.77, "reasoning": "Unknown category id."},
                {"id": fuel.id, "type": "transfer", "confidence": 0.72, "reasoning": "Transfer should be filtered."},
                {"id": shopping.id, "type": "expense", "confidence": 0.60, "reasoning": "Valid shopping backup."},
            ]
        }
    )
    ai = StubCategorizer(["not a json payload", repaired])

    candidates = await ai.suggest_category_candidates(
        REAL_FOOD_TX,
        db_session,
        min_candidates=3,
        expected_type="expense",
    )

    assert len(ai.prompts) == 2  # original + repair prompt
    assert len(candidates) >= 3
    ids = [c["id"] for c in candidates]
    assert len(ids) == len(set(ids))
    assert all(c["type"] == "expense" for c in candidates)
    assert food.id in ids
    assert salary.id not in ids


@pytest.mark.asyncio
async def test_update_transaction_category_sets_reflection_and_finalized_decision_state(db_session):
    account, cats = await _seed_core_reference_data(db_session)
    fuel = cats["Transportation>Fuel>expense"]
    food = cats["Entertainment>Food>expense"]

    tx = Transaction(
        date=datetime(2026, 2, 10),
        description=REAL_FUEL_TX,
        amount=7.50,
        type="expense",
        account_id=account.id,
        category_id=fuel.id,
        is_verified=False,
        decision_state="needs_review",
        review_priority=50,
        review_bucket="conf_mid",
    )
    db_session.add(tx)
    await db_session.flush()
    db_session.add(
        AIMemory(
            transaction_id=tx.id,
            pattern_key="UNITED ANKETELL NTH",
            ai_suggested_category_id=fuel.id,
            ai_reasoning="Fuel station signal",
        )
    )
    await db_session.commit()

    with patch("src.commands.CategorizerAI") as mock_ai_cls:
        mock_ai = mock_ai_cls.return_value
        mock_ai.generate_reflection = AsyncMock(
            return_value="When merchant indicates food chain, use Food."
        )
        ok, msg = await update_transaction_category(db_session, tx.id, category_id=food.id)

    assert ok is True
    assert "updated and verified" in msg.lower()

    tx_row = (
        await db_session.execute(select(Transaction).where(Transaction.id == tx.id))
    ).scalar_one()
    mem_row = (
        await db_session.execute(select(AIMemory).where(AIMemory.transaction_id == tx.id))
    ).scalar_one()

    assert tx_row.is_verified is True
    assert tx_row.category_id == food.id
    assert tx_row.decision_state == "auto_approved"
    assert tx_row.review_priority == 100
    assert tx_row.review_bucket == "manual_review"
    assert mem_row.user_selected_category_id == food.id
    assert mem_row.reflection == "When merchant indicates food chain, use Food."


@pytest.mark.asyncio
async def test_rebuild_category_understanding_from_real_transactions(db_session):
    account, cats = await _seed_core_reference_data(db_session)
    grocery = cats["Household>Grocery>expense"]

    db_session.add_all(
        [
            Transaction(
                date=datetime(2026, 1, 29),
                description=REAL_GROCERY_TX,
                amount=18.60,
                type="expense",
                account_id=account.id,
                category_id=grocery.id,
                is_verified=True,
            ),
            Transaction(
                date=datetime(2026, 1, 24),
                description="Tucker Fresh",
                amount=5.99,
                type="expense",
                account_id=account.id,
                category_id=grocery.id,
                is_verified=True,
            ),
        ]
    )
    await db_session.commit()

    updated = await rebuild_category_understanding(db_session, category_ids=[grocery.id])
    await db_session.commit()
    assert updated == 1

    profile = (
        await db_session.execute(
            select(AICategoryUnderstanding).where(AICategoryUnderstanding.category_id == grocery.id)
        )
    ).scalar_one()

    payload = json.loads(profile.sample_transactions_json)
    assert "Category intent profile for" in profile.understanding
    assert "Verified examples: 2" in profile.understanding
    assert len(payload["samples"]) >= 2
    assert isinstance(payload["patterns"], list)


@pytest.mark.asyncio
async def test_add_transaction_ai_reasoning_persists_to_memory_with_review_metadata(db_session):
    account_name = f"Cash-{uuid4().hex[:8]}"
    category_name = f"Food-{uuid4().hex[:6]}"

    await add_account(db_session, account_name, "Manual")
    await add_category(db_session, category_name, "Entertainment", "expense")
    cat = (
        await db_session.execute(
            select(Category).where(
                Category.name == category_name,
                Category.parent_name == "Entertainment",
                Category.type == "expense",
            )
        )
    ).scalar_one()

    with patch("src.commands.CategorizerAI") as mock_ai_cls:
        mock_ai = mock_ai_cls.return_value
        mock_ai.suggest_category = AsyncMock(
            return_value=(
                cat.id,
                0.75,
                "Merchant 'Hungry Jacks' indicates food/restaurant spend.",
                "expense",
            )
        )
        success, _, tx = await add_transaction(
            db_session,
            date=datetime(2026, 2, 16),
            amount=31.30,
            description=REAL_FOOD_TX,
            account_name=account_name,
        )

    assert success is True
    assert tx.category_id == cat.id
    assert tx.decision_state == "needs_review"  # confidence band [0.70, 0.97)
    assert tx.is_verified is False

    mem = (
        await db_session.execute(select(AIMemory).where(AIMemory.transaction_id == tx.id))
    ).scalar_one()
    assert "Hungry Jacks" in mem.ai_reasoning
    assert mem.ai_suggested_category_id == cat.id
    assert mem.policy_version is not None
    assert mem.threshold_used is not None


@pytest.mark.asyncio
async def test_suggest_category_prefers_exact_verified_transfer_precedent_over_income_guess(db_session):
    account, _ = await _seed_core_reference_data(db_session)
    desc = "TRANSFER FROM SOMANGILI SIVAKU JOINT BANK TRANSFE"

    db_session.add(
        Transaction(
            date=datetime(2026, 1, 8),
            description=desc,
            amount=100.0,
            type="transfer",
            account_id=account.id,
            category_id=None,
            is_verified=True,
        )
    )
    await db_session.commit()

    ai = StubCategorizer(
        [
            json.dumps(
                {
                    "candidates": [
                        {
                            "id": 999,
                            "type": "income",
                            "confidence": 0.99,
                            "reasoning": "Should never be used if precedent works.",
                        }
                    ]
                }
            )
        ]
    )
    cat_id, conf, reason, tx_type = await ai.suggest_category(desc, db_session, expected_type="income")
    assert tx_type == "transfer"
    assert cat_id is None
    assert conf >= 0.9
    assert "Exact verified precedent match" in reason
    assert ai.prompts == []  # no LLM call when precedent is exact and strong


@pytest.mark.asyncio
async def test_suggest_category_prefers_keyword_verified_precedent_before_llm(db_session):
    account, cats = await _seed_core_reference_data(db_session)
    grocery = cats["Household>Grocery>expense"]
    desc_seed = "ZXQSHOP MARKET 10FEB26 VISA AUD ZXQSHOP AU"

    db_session.add_all(
        [
            Transaction(
                date=datetime(2026, 2, 10),
                description=desc_seed,
                amount=-74.80,
                type="expense",
                account_id=account.id,
                category_id=grocery.id,
                is_verified=True,
            ),
            Transaction(
                date=datetime(2026, 2, 11),
                description="VISA DEBIT PURCHASE CARD 8208 ZXQSHOP MARKET/ SUBURB",
                amount=-45.20,
                type="expense",
                account_id=account.id,
                category_id=grocery.id,
                is_verified=True,
            ),
            Transaction(
                date=datetime(2026, 2, 12),
                description="ZXQSHOP MARKET 12FEB26 VISA AUD ZXQSHOP AU",
                amount=-31.10,
                type="expense",
                account_id=account.id,
                category_id=grocery.id,
                is_verified=True,
            ),
        ]
    )
    await db_session.commit()

    ai = StubCategorizer(
        [
            json.dumps(
                {
                    "candidates": [
                        {
                            "id": cats["Entertainment>Food>expense"].id,
                            "type": "expense",
                            "confidence": 0.99,
                            "reasoning": "Should not be used when keyword precedent is strong.",
                        }
                    ]
                }
            )
        ]
    )
    cat_id, conf, reason, tx_type = await ai.suggest_category(
        "ZXQSHOP MARKET 14FEB26 CARD 8208",
        db_session,
        expected_type="expense",
        amount_hint=-27.50,
    )

    assert tx_type == "expense"
    assert cat_id == grocery.id
    assert conf >= 0.9
    assert (
        "Keyword verified precedent" in reason
        or "Merchant category precedent" in reason
    )
    assert ai.prompts == []  # no LLM call when deterministic keyword precedent is strong


@pytest.mark.asyncio
async def test_internal_transfer_heuristic_does_not_override_salary_rows(db_session):
    _, cats = await _seed_core_reference_data(db_session)
    salary = cats["Employer>Salary>income"]

    payload = json.dumps(
        {
            "candidates": [
                {"id": salary.id, "type": "income", "confidence": 0.95, "reasoning": "Salary signal."}
            ]
        }
    )
    ai = StubCategorizer([payload])
    desc = "TRANSFER Aurizn Salary Aurizn Defence P 0272635 Z@LC03712 SYSTEM GENERATED"
    cat_id, conf, reason, tx_type = await ai.suggest_category(desc, db_session, expected_type="income")

    assert tx_type == "income"
    assert cat_id == salary.id
    assert conf > 0.9
    assert ai.prompts  # salary should go through normal candidate path, not transfer shortcut


@pytest.mark.asyncio
async def test_external_transfer_markers_do_not_trigger_internal_transfer_shortcut(db_session):
    _, cats = await _seed_core_reference_data(db_session)
    expense_transfer = cats["Others>Transfer>expense"]

    payload = json.dumps(
        {
            "candidates": [
                {
                    "id": expense_transfer.id,
                    "type": "expense",
                    "confidence": 0.88,
                    "reasoning": "External transfer-like expense in configured taxonomy.",
                }
            ]
        }
    )
    ai = StubCategorizer([payload])
    desc = (
        "TRANSFER RTP 067872 27775224 NOTPROVIDED HKBAAU2SXXXN20260118 "
        "INTERNET BANKING"
    )
    cat_id, conf, _reason, tx_type = await ai.suggest_category(
        desc,
        db_session,
        expected_type="expense",
    )

    assert tx_type == "expense"
    assert cat_id == expense_transfer.id
    assert conf >= 0.8
    assert ai.prompts  # should pass through candidate path, not internal transfer shortcut


@pytest.mark.asyncio
async def test_probable_transfer_rail_shortcut_when_expected_type_unknown(db_session):
    ai = StubCategorizer(
        [
            json.dumps(
                {
                    "candidates": [
                        {"id": 999, "type": "income", "confidence": 0.99, "reasoning": "Should not be used."}
                    ]
                }
            )
        ]
    )
    desc = (
        "TRANSFER RTP 774001 214179124 NOTPROVIDED HKBAAU2SXXXN20251201000000055578740 "
        "Wise Transfer YRTM90673 INTERNET BANKING"
    )
    cat_id, conf, reason, tx_type = await ai.suggest_category(
        desc,
        db_session,
        expected_type=None,
    )
    assert tx_type == "transfer"
    assert cat_id is None
    assert conf >= 0.9
    assert "Probable transfer rails detected" in reason
    assert ai.prompts == []  # deterministic shortcut; no LLM call


@pytest.mark.asyncio
async def test_merchant_category_precedent_uses_verified_and_benchmark_consensus(db_session):
    account, cats = await _seed_core_reference_data(db_session)
    shopping = cats["Entertainment>Shopping>expense"]

    db_session.add_all(
        [
            Transaction(
                date=datetime(2026, 1, 2),
                description="SUPER CHEAP AUTO ROCKINGHAM",
                amount=-45.0,
                type="expense",
                account_id=account.id,
                category_id=shopping.id,
                is_verified=True,
            ),
            CategoryBenchmarkItem(
                description="SUPER CHEAP AUTO 08JAN26 VISA AUD SUPER CHEAP AUTO ROCKINGHAM AU",
                expected_category_id=shopping.id,
                expected_parent_name="Entertainment",
                expected_category_name="Shopping",
                expected_type="expense",
                source_file="unit-merchant-precedent",
                label_source="manual_label",
            ),
            CategoryBenchmarkItem(
                description="SUPER CHEAP AUTO 20JAN26 VISA AUD SUPER CHEAP AUTO AU",
                expected_category_id=shopping.id,
                expected_parent_name="Entertainment",
                expected_category_name="Shopping",
                expected_type="expense",
                source_file="unit-merchant-precedent",
                label_source="manual_label",
            ),
        ]
    )
    await db_session.commit()

    ai = StubCategorizer(
        [
            json.dumps(
                {
                    "candidates": [
                        {
                            "id": cats["Transportation>Fuel>expense"].id,
                            "type": "expense",
                            "confidence": 0.99,
                            "reasoning": "Should not be used when merchant precedent is strong.",
                        }
                    ]
                }
            )
        ]
    )
    cat_id, conf, reason, tx_type = await ai.suggest_category(
        "SUPER CHEAP AUTO 08JAN26 ATMA896 19:26:19 VISA AUD ROCKINGHAM AU",
        db_session,
        expected_type="expense",
    )
    assert tx_type == "expense"
    assert cat_id == shopping.id
    assert conf >= 0.85
    assert "Merchant category precedent" in reason
    assert ai.prompts == []  # deterministic precedent path should avoid LLM call
