import json
from datetime import datetime
import unittest

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - only for unittest-only envs
    raise unittest.SkipTest("pytest is required for this module")
from sqlalchemy import delete, select

from src.ai import CategorizerAI
from src.database import Category, MerchantKeywordAlias
from src.keyword_resolver import KeywordResolver
from src.patterns import extract_pattern_key_result


INTERNAL_TRANSFER_TX = (
    "TRANSFER LP SDB60271Y ANZ Joint Account 665889369 "
    "Joint Bank Transfe YIB153034 INTERNET BANKING"
)
EXTERNAL_TRANSFER_EXPENSE_TX = "PAYMENT TO S KARLAPUDI #044193"

NOISY_WOOLWORTHS_VARIANTS = [
    "VISA DEBIT PURCHASE CARD 8208 WOOLWORTHS/ NICHOLSON RD & CANNINGVALE",
    (
        "WOOLWORTHS/NICHOLSON RD 05FEB26 ATMA896 21:46:24 4402 VISA AUD "
        "WOOLWORTHS/NICHOLSON RD 754643&CANNINGVALE AU A88842514 ATM"
    ),
]

NOISY_HUNGRY_JACKS_VARIANTS = [
    (
        "HUNGRY JACKS 05JAN26 ATMA896 20:06:11 4402 VISA AUD "
        "Hungry Jacks 126058 Livingston AU A88824047 ATM"
    ),
    (
        "HUNGRY JACKS 09JAN26 ATMA896 00:39:09 4402 VISA AUD "
        "Hungry Jacks 052818 Livingston AU A88818753 ATM"
    ),
]


class StubCategorizer(CategorizerAI):
    def __init__(self, responses):
        self.responses = list(responses)
        self.model = "test-model"
        self.client = None

    async def _chat_once(self, prompt):
        if not self.responses:
            raise AssertionError("No stubbed response left for _chat_once")
        return self.responses.pop(0)

    def _run_web_search(self, query, max_results=3):
        return []


def test_internal_vs_external_transfer_keyword_semantics():
    internal = extract_pattern_key_result(INTERNAL_TRANSFER_TX)
    external = extract_pattern_key_result(EXTERNAL_TRANSFER_EXPENSE_TX)

    assert internal.source == "rule"
    assert external.source == "rule"
    assert external.confidence > internal.confidence

    # Internal transfer keeps account context; external keeps payee identity.
    assert "ANZ" in internal.keyword
    assert "KARLAPUDI" in external.keyword
    assert "KARLAPUDI" not in internal.keyword


def test_processor_noise_heavy_merchants_keep_stable_supermarket_signal():
    results = [extract_pattern_key_result(v) for v in NOISY_WOOLWORTHS_VARIANTS]
    assert all(r.source == "rule" for r in results)
    assert all(r.confidence >= 0.8 for r in results)
    assert all(r.keyword.startswith("WOOLWORTHS") for r in results)


def test_processor_noise_heavy_merchants_keep_stable_food_signal():
    results = [extract_pattern_key_result(v) for v in NOISY_HUNGRY_JACKS_VARIANTS]
    assert all(r.keyword == "HUNGRY JACKS" for r in results)
    assert all(r.source == "rule" for r in results)
    assert all(r.confidence >= 0.8 for r in results)


@pytest.mark.asyncio
async def test_resolver_collapses_noisy_alias_variants_into_one_merchant_phrase(db_session):
    resolver = KeywordResolver()
    for i, text in enumerate(NOISY_HUNGRY_JACKS_VARIANTS, start=1):
        ok = await resolver.learn_from_verified(
            db_session,
            text,
            resolved_keyword="HUNGRY JACKS",
            transaction_id=9000 + i,
        )
        assert ok is True
    await db_session.commit()

    rows = await db_session.execute(
        select(MerchantKeywordAlias).where(MerchantKeywordAlias.canonical_keyword == "HUNGRY JACKS")
    )
    aliases = rows.scalars().all()
    assert len(aliases) == 1
    assert aliases[0].normalized_phrase == "HUNGRY JACKS"
    assert aliases[0].support_count >= 2


@pytest.mark.asyncio
async def test_resolver_prefers_high_verified_alias_when_phrase_is_ambiguous(db_session):
    # Both aliases map from same normalized phrase; resolver should choose the more verified one.
    db_session.add_all(
        [
            MerchantKeywordAlias(
                normalized_phrase="WOOLWORTHS",
                canonical_keyword="HOUSEHOLD_GROCERY",
                support_count=12,
                verified_count=12,
                last_seen_at=datetime.utcnow(),
            ),
            MerchantKeywordAlias(
                normalized_phrase="WOOLWORTHS",
                canonical_keyword="ENTERTAINMENT_SHOPPING",
                support_count=3,
                verified_count=1,
                last_seen_at=datetime.utcnow(),
            ),
        ]
    )
    await db_session.commit()

    resolver = KeywordResolver()
    result = await resolver.resolve(NOISY_WOOLWORTHS_VARIANTS[0], db_session)
    assert result.source == "learned_alias"
    assert result.keyword == "HOUSEHOLD_GROCERY"
    assert result.confidence >= 0.6


@pytest.mark.asyncio
async def test_resolver_near_match_with_generic_phrase_prefers_most_verified_alias(db_session):
    # With a highly generic phrase ("UNITED"), overlap is not enough to distinguish intent.
    # Current resolver behavior is to favor the more verified alias deterministically.
    await db_session.execute(delete(MerchantKeywordAlias))
    await db_session.commit()
    db_session.add_all(
        [
            MerchantKeywordAlias(
                normalized_phrase="UNITED ANKETELL NTH",
                canonical_keyword="TRANSPORTATION_FUEL",
                support_count=8,
                verified_count=8,
                last_seen_at=datetime.utcnow(),
            ),
            MerchantKeywordAlias(
                normalized_phrase="UNITED FITNESS",
                canonical_keyword="GYM_MEMBERSHIP",
                support_count=20,
                verified_count=20,
                last_seen_at=datetime.utcnow(),
            ),
        ]
    )
    await db_session.commit()

    resolver = KeywordResolver()
    result = await resolver.resolve("UNITED ANKETELL", db_session)
    assert result.source == "learned_alias"
    assert result.keyword == "GYM_MEMBERSHIP"


@pytest.mark.asyncio
async def test_candidate_normalization_avoids_transfer_type_for_external_expense_context(db_session):
    # Edge case: model emits a high-confidence transfer-type candidate for an external payment.
    # With expected_type='expense', normalization must keep only valid expense categories.
    transfer_expense = Category(name="Transfer", parent_name="Others", type="expense")
    food = Category(name="Food", parent_name="Entertainment", type="expense")
    db_session.add_all([transfer_expense, food])
    await db_session.commit()

    model_payload = json.dumps(
        {
            "candidates": [
                {"id": transfer_expense.id, "type": "transfer", "confidence": 0.98, "reasoning": "looks like transfer"},
                {
                    "id": transfer_expense.id,
                    "type": "expense",
                    "confidence": 0.82,
                    "reasoning": "external payment to person; taxonomy tracks as expense transfer",
                },
                {"id": food.id, "type": "expense", "confidence": 0.20, "reasoning": "fallback"},
            ]
        }
    )
    ai = StubCategorizer([model_payload])

    candidates = await ai.suggest_category_candidates(
        EXTERNAL_TRANSFER_EXPENSE_TX,
        db_session,
        min_candidates=2,
        expected_type="expense",
    )
    assert len(candidates) >= 2
    assert all(c["type"] == "expense" for c in candidates)
    assert candidates[0]["id"] == transfer_expense.id
