from datetime import datetime
import math
import re
import json
from sqlalchemy import select, delete

from src.database import MerchantKeywordAlias
from src.patterns import PatternKeyResult, extract_pattern_key_result


SPACE_RE = re.compile(r"\s+")


def _normalize_phrase(text: str) -> str:
    # Normalize to semantic merchant/payee key rather than raw statement text.
    # This collapses timestamp/reference variants into one alias phrase.
    key = extract_pattern_key_result(text).keyword
    cleaned = SPACE_RE.sub(" ", (key or "").upper()).strip()
    return cleaned[:120] if cleaned else "UNKNOWN"


class KeywordResolver:
    def __init__(self, low_confidence_threshold: float = 0.35):
        self.low_confidence_threshold = low_confidence_threshold

    async def resolve(self, description: str, session) -> PatternKeyResult:
        rule_result = extract_pattern_key_result(description)
        if rule_result.confidence >= 0.85:
            return rule_result

        normalized = _normalize_phrase(description)
        if not normalized:
            return PatternKeyResult("UNKNOWN", 0.0, "fallback", [])

        # 1) Exact learned alias match.
        stmt = (
            select(MerchantKeywordAlias)
            .where(MerchantKeywordAlias.normalized_phrase == normalized)
            .order_by(
                MerchantKeywordAlias.verified_count.desc(),
                MerchantKeywordAlias.support_count.desc(),
                MerchantKeywordAlias.last_seen_at.desc(),
            )
            .limit(1)
        )
        res = await session.execute(stmt)
        row = res.scalar_one_or_none()
        if row:
            conf = min(0.95, 0.65 + math.log10(max(1, row.verified_count)) * 0.2)
            return PatternKeyResult(
                keyword=row.canonical_keyword,
                confidence=conf,
                source="learned_alias",
                tokens_used=row.canonical_keyword.split()[:8],
            )

        # 2) Near match via token overlap on recent learned aliases.
        candidates_stmt = (
            select(MerchantKeywordAlias)
            .order_by(MerchantKeywordAlias.verified_count.desc(), MerchantKeywordAlias.support_count.desc())
            .limit(250)
        )
        c_res = await session.execute(candidates_stmt)
        rows = c_res.scalars().all()

        input_tokens = set(normalized.split())
        best = None
        best_score = 0.0
        for r in rows:
            alias_tokens = set((r.normalized_phrase or "").split())
            if not alias_tokens:
                continue
            overlap = len(input_tokens & alias_tokens) / max(1, len(input_tokens | alias_tokens))
            weighted = overlap * (1.0 + min(1.0, r.verified_count / 20.0))
            if weighted > best_score:
                best_score = weighted
                best = r

        if best and best_score >= 0.45:
            conf = min(0.88, 0.50 + best_score * 0.35)
            return PatternKeyResult(
                keyword=best.canonical_keyword,
                confidence=conf,
                source="learned_alias",
                tokens_used=best.canonical_keyword.split()[:8],
            )

        # 3) Fallback to deterministic result.
        return rule_result

    def _append_transaction_source(self, row, transaction_id=None, description=None, max_items: int = 200):
        payload = {}
        if row.metadata_json:
            try:
                payload = json.loads(row.metadata_json)
            except Exception:
                payload = {}

        sources = payload.get("source_transactions")
        if not isinstance(sources, list):
            sources = []

        entry = {}
        if transaction_id is not None:
            entry["transaction_id"] = int(transaction_id)
        if description:
            entry["description"] = str(description)[:400]

        if entry:
            existing_ids = {s.get("transaction_id") for s in sources if isinstance(s, dict) and s.get("transaction_id") is not None}
            if "transaction_id" in entry and entry["transaction_id"] in existing_ids:
                # Refresh description for existing tx id if needed.
                for s in sources:
                    if isinstance(s, dict) and s.get("transaction_id") == entry["transaction_id"] and entry.get("description"):
                        s["description"] = entry["description"]
                        break
            else:
                sources.append(entry)

        if len(sources) > max_items:
            sources = sources[-max_items:]

        payload["source_transactions"] = sources
        row.metadata_json = json.dumps(payload, ensure_ascii=True)

    async def learn_from_verified(self, session, description: str, resolved_keyword: str = None, transaction_id: int = None):
        if not description:
            return False
        phrase = _normalize_phrase(description)
        if not phrase:
            return False

        canonical = (resolved_keyword or extract_pattern_key_result(description).keyword or "UNKNOWN").upper().strip()
        if not canonical:
            canonical = "UNKNOWN"

        stmt = select(MerchantKeywordAlias).where(
            MerchantKeywordAlias.normalized_phrase == phrase,
            MerchantKeywordAlias.canonical_keyword == canonical,
        )
        res = await session.execute(stmt)
        row = res.scalar_one_or_none()
        now = datetime.utcnow()
        if row:
            row.support_count = int(row.support_count or 0) + 1
            row.verified_count = int(row.verified_count or 0) + 1
            row.last_seen_at = now
            self._append_transaction_source(row, transaction_id=transaction_id, description=description)
            session.add(row)
        else:
            metadata_payload = {"source_transactions": []}
            if transaction_id is not None:
                metadata_payload["source_transactions"].append(
                    {"transaction_id": int(transaction_id), "description": str(description)[:400]}
                )
            session.add(
                MerchantKeywordAlias(
                    normalized_phrase=phrase,
                    canonical_keyword=canonical[:80],
                    support_count=1,
                    verified_count=1,
                    last_seen_at=now,
                    metadata_json=json.dumps(metadata_payload, ensure_ascii=True),
                )
            )
        return True

    async def backfill_from_verified_transactions(self, session, reset_existing: bool = True):
        from src.database import Transaction

        if reset_existing:
            await session.execute(delete(MerchantKeywordAlias))
            await session.commit()

        rows = await session.execute(
            select(Transaction).where(Transaction.is_verified.is_(True)).order_by(Transaction.id.asc())
        )
        txs = rows.scalars().all()
        count = 0
        for tx in txs:
            ok = await self.learn_from_verified(session, tx.description, transaction_id=tx.id)
            if ok:
                count += 1
        await session.commit()
        return {"seen_verified": len(txs), "learned_updates": count}

    async def debug(self, session, description: str):
        rule = extract_pattern_key_result(description)
        resolved = await self.resolve(description, session)
        normalized = _normalize_phrase(description)

        exact_stmt = (
            select(MerchantKeywordAlias)
            .where(MerchantKeywordAlias.normalized_phrase == normalized)
            .order_by(MerchantKeywordAlias.verified_count.desc(), MerchantKeywordAlias.support_count.desc())
            .limit(5)
        )
        exact_res = await session.execute(exact_stmt)
        exact_rows = exact_res.scalars().all()

        return {
            "description": description,
            "normalized_phrase": normalized,
            "rule_result": rule,
            "resolved_result": resolved,
            "exact_alias_matches": [
                {
                    "canonical_keyword": r.canonical_keyword,
                    "support_count": r.support_count,
                    "verified_count": r.verified_count,
                    "metadata_json": r.metadata_json,
                }
                for r in exact_rows
            ],
        }
