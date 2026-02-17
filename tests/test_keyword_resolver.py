import pytest
import pytest_asyncio
import json

from src.keyword_resolver import KeywordResolver
from src.database import MerchantKeywordAlias
from sqlalchemy import select


@pytest.mark.asyncio
async def test_learn_from_verified_creates_alias(db_session):
    resolver = KeywordResolver()
    ok = await resolver.learn_from_verified(
        db_session,
        "PAYMENT FROM MISS ADITHYA SUNIL",
        resolved_keyword="MISS ADITHYA SUNIL",
        transaction_id=101,
    )
    assert ok is True
    await db_session.commit()

    row = await db_session.execute(
        select(MerchantKeywordAlias).where(MerchantKeywordAlias.canonical_keyword == "MISS ADITHYA SUNIL")
    )
    alias = row.scalar_one_or_none()
    assert alias is not None
    assert alias.verified_count >= 1
    meta = json.loads(alias.metadata_json or "{}")
    assert "source_transactions" in meta
    assert any(s.get("transaction_id") == 101 for s in meta.get("source_transactions", []))


@pytest.mark.asyncio
async def test_resolve_uses_exact_alias_match(db_session):
    resolver = KeywordResolver()
    await resolver.learn_from_verified(
        db_session,
        "VISA DEBIT PURCHASE CARD 8208 WOOLWORTHS/ NICHOLSON RD",
        resolved_keyword="WOOLWORTHS",
    )
    await db_session.commit()

    result = await resolver.resolve("VISA DEBIT PURCHASE CARD 9200 WOOLWORTHS/ NICHOLSON RD", db_session)
    assert result.keyword == "WOOLWORTHS"
    assert result.confidence >= 0.5


@pytest.mark.asyncio
async def test_normalization_collapses_reference_variants(db_session):
    resolver = KeywordResolver()
    d1 = "DF PAINTBALL 24JAN26 ATMA896 14:59:02 4402 VISA AUD DF PAINTBALL 818755 BALDIVIS AU A88822674 ATM"
    d2 = "DF PAINTBALL 24JAN26 ATMA896 14:48:42 4402 VISA AUD DF PAINTBALL 585530 BALDIVIS AU A88822673 ATM"

    await resolver.learn_from_verified(db_session, d1, resolved_keyword="DF PAINTBALL", transaction_id=201)
    await resolver.learn_from_verified(db_session, d2, resolved_keyword="DF PAINTBALL", transaction_id=202)
    await db_session.commit()

    rows = await db_session.execute(
        select(MerchantKeywordAlias).where(MerchantKeywordAlias.canonical_keyword == "DF PAINTBALL")
    )
    aliases = rows.scalars().all()
    assert len(aliases) == 1
    assert aliases[0].support_count >= 2
    assert aliases[0].normalized_phrase == "DF PAINTBALL"
    meta = json.loads(aliases[0].metadata_json or "{}")
    source_ids = {s.get("transaction_id") for s in meta.get("source_transactions", [])}
    assert 201 in source_ids and 202 in source_ids


@pytest.mark.asyncio
async def test_resolve_fallback_for_empty_description(db_session):
    resolver = KeywordResolver()
    result = await resolver.resolve("", db_session)
    assert result.keyword == "UNKNOWN"
    assert result.confidence == 0.0
