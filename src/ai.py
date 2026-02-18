import ollama
import re
from collections import Counter
from sqlalchemy import select
from src.database import (
    Category,
    Transaction,
    AIMemory,
    AIGlobalMemory,
    AICategoryUnderstanding,
    CategoryBenchmarkItem,
)
from src.keyword_resolver import KeywordResolver

from src.ai_config import get_ollama_client

class CategorizerAI:
    def __init__(self, model="llama3.1:8b"):
        """
        Initialize with the Ollama model.
        Ensure 'ollama serve' is running and the model is pulled.
        """
        self.model = model
        self.client = get_ollama_client()

    async def _chat_once(self, prompt):
        response = await self.client.chat(model=self.model, messages=[
            {'role': 'user', 'content': prompt}
        ], options={"temperature": 0.0})
        return response['message']['content'].strip()

    def _clean_description(self, description):
        clean_desc = re.sub(r'\d{2}[A-Z]{3}\d{2}', '', description) # 28JAN26
        clean_desc = re.sub(r'\d{2}:\d{2}:\d{2}', '', clean_desc) # 23:30:46
        clean_desc = re.sub(r'\b\d{4}\b', '', clean_desc)
        clean_desc = re.sub(r'\b[A-Z0-9]{6,}\b', '', clean_desc)
        clean_desc = re.sub(r'\b(VISA|AUD|ATMA\d*|EFTPOS|DEBIT|CREDIT)\b', '', clean_desc, flags=re.IGNORECASE)
        clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
        return clean_desc

    def _run_web_search(self, query, max_results=3):
        if not query or not str(query).strip():
            return []
        try:
            try:
                from ddgs import DDGS
            except Exception:
                # Backward-compat fallback for older environments.
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                return list(ddgs.text(str(query).strip(), max_results=max_results))
        except Exception:
            return []

    def _format_search_results(self, results):
        if not results:
            return "No information found."
        lines = []
        for r in results:
            title = r.get("title", "Unknown")
            body = r.get("body", "")
            href = r.get("href", "")
            lines.append(f"- {title}: {body} {href}".strip())
        return "\n".join(lines)

    def _is_internal_transfer_text(self, description: str) -> bool:
        text = (description or "").upper()
        if "TRANSFER" not in text:
            return False
        # Guard against payroll/income phrases.
        if any(k in text for k in {"SALARY", "PAYROLL", "WAGE", "BONUS"}):
            return False
        # Strong cues for own-account movement.
        strong_internal_markers = {
            "JOINT ACCOUNT",
            "JOINT BANK TRANSFE",
            "OWN ACCOUNT",
            "BETWEEN ACCOUNTS",
            "ACCOUNT TRANSFER",
            "INTERNAL TRANSFER",
            "TO SAVINGS",
            "FROM SAVINGS",
        }
        if any(m in text for m in strong_internal_markers):
            return True

        # External transfer markers should not be auto-classified as internal transfers.
        external_markers = {
            "RTP",
            "SWIFT",
            " BIC ",
            "OSKO",
            "PAYID",
            "NOTPROVIDED",
        }
        if any(m in f" {text} " for m in external_markers):
            return False

        # INTERNET BANKING by itself is too broad; require at least one stronger co-cue.
        if "INTERNET BANKING" in text:
            co_cues = {"JOINT", "OWN", "BETWEEN ACCOUNTS", "SAVINGS"}
            return any(c in text for c in co_cues)

        return False

    def _looks_like_probable_transfer(self, description: str) -> bool:
        """
        Detect probable transfer/payment-rail movements that should be typed as transfer
        when expected type is unknown.
        """
        text = f" {(description or '').upper()} "
        if "TRANSFER" not in text:
            return False

        transfer_rail_markers = {
            " RTP ",
            "WISE TRANSFER",
            " OSKO ",
            " PAYID ",
            " SWIFT ",
            " BIC ",
            " NOTPROVIDED ",
        }
        if not any(m in text for m in transfer_rail_markers):
            return False

        # Avoid false positives for card-purchase statement noise.
        card_purchase_markers = {
            " VISA ",
            " EFTPOS ",
            " ATM ",
            " CARD ",
            " PURCHASE ",
            " DEBIT ",
            " CREDIT ",
            " PAYPAL *",
        }
        if any(m in text for m in card_purchase_markers):
            return False

        return True

    async def _get_exact_verified_precedent(self, description, session):
        desc = (description or "").strip()
        if not desc:
            return None
        stmt = (
            select(Transaction)
            .where(
                Transaction.description.ilike(desc),
                Transaction.is_verified.is_(True),
            )
            .order_by(Transaction.date.desc())
            .limit(30)
        )
        res = await session.execute(stmt)
        rows = res.scalars().all()
        if not rows:
            return None

        keys = []
        for tx in rows:
            tx_type = (tx.type or "").lower()
            if tx_type == "transfer" and tx.category_id is None:
                keys.append(("transfer", None))
            elif tx.category_id and tx_type in {"expense", "income"}:
                keys.append((tx_type, int(tx.category_id)))

        if not keys:
            return None

        counts = Counter(keys)
        (top_type, top_cat), top_count = counts.most_common(1)[0]
        ratio = top_count / max(1, len(keys))
        # Require strong consensus to avoid locking onto mixed legacy data.
        if ratio < 0.70:
            return None

        return {
            "type": top_type,
            "category_id": top_cat,
            "confidence": min(0.99, 0.90 + (ratio * 0.09)),
            "reasoning": f"Exact verified precedent match ({top_count}/{len(keys)} rows).",
        }

    def _amount_sign(self, amount):
        if amount is None:
            return None
        try:
            value = float(amount)
        except Exception:
            return None
        if value > 0:
            return "positive"
        if value < 0:
            return "negative"
        return "zero"

    async def _get_keyword_verified_precedent(self, description, session, expected_type=None, amount_hint=None):
        """
        Deterministic precedent by merchant keyword + amount sign + type.
        Uses only verified rows.
        """
        resolver = KeywordResolver()
        resolved = await resolver.resolve(description, session)
        keyword = (resolved.keyword or "").strip()
        if len(keyword) < 3 or keyword == "UNKNOWN" or float(resolved.confidence or 0.0) < 0.35:
            return None

        stmt = (
            select(Transaction)
            .where(
                Transaction.is_verified.is_(True),
                Transaction.category_id.is_not(None),
                Transaction.description.ilike(f"%{keyword}%"),
            )
            .order_by(Transaction.date.desc())
            .limit(120)
        )
        expected_type = (expected_type or "").strip().lower()
        if expected_type in {"expense", "income"}:
            stmt = stmt.where(Transaction.type == expected_type)

        res = await session.execute(stmt)
        rows = res.scalars().all()
        if not rows:
            return None

        current_sign = self._amount_sign(amount_hint)
        keys = []
        for tx in rows:
            tx_type = (tx.type or "").lower()
            if tx_type not in {"expense", "income"} or not tx.category_id:
                continue
            tx_sign = self._amount_sign(tx.amount)
            if current_sign and tx_sign and tx_sign != current_sign:
                continue
            keys.append((tx_type, int(tx.category_id)))

        # If sign filter is too strict, relax sign matching.
        if len(keys) < 3:
            keys = []
            for tx in rows:
                tx_type = (tx.type or "").lower()
                if tx_type not in {"expense", "income"} or not tx.category_id:
                    continue
                keys.append((tx_type, int(tx.category_id)))

        if len(keys) < 3:
            return None

        counts = Counter(keys)
        (top_type, top_cat), top_count = counts.most_common(1)[0]
        ratio = top_count / max(1, len(keys))
        if top_count < 3 or ratio < 0.70:
            return None

        conf = min(0.98, 0.82 + (ratio * 0.12) + (min(top_count, 10) * 0.004))
        return {
            "type": top_type,
            "category_id": top_cat,
            "confidence": conf,
            "reasoning": (
                f"Keyword verified precedent ({keyword}): "
                f"{top_count}/{len(keys)} verified rows matched."
            ),
        }

    async def _get_merchant_category_precedent(self, description, session, expected_type=None):
        """
        Consensus precedent across verified transactions + labeled benchmark rows.
        """
        resolver = KeywordResolver()
        resolved = await resolver.resolve(description, session)
        keyword = (resolved.keyword or "").strip().upper()
        if len(keyword) < 3 or keyword in {
            "UNKNOWN",
            "TRANSFER",
            "PAYMENT",
            "VISA",
            "DEBIT",
            "CREDIT",
            "PURCHASE",
            "ATM",
            "EFTPOS",
            "CARD",
        }:
            return None

        expected_type = (expected_type or "").strip().lower()
        if expected_type not in {"expense", "income"}:
            expected_type = None

        weighted_counts = Counter()
        verified_count = 0
        benchmark_count = 0

        tx_stmt = (
            select(Transaction)
            .where(
                Transaction.is_verified.is_(True),
                Transaction.category_id.is_not(None),
                Transaction.description.ilike(f"%{keyword}%"),
            )
            .order_by(Transaction.date.desc())
            .limit(200)
        )
        if expected_type:
            tx_stmt = tx_stmt.where(Transaction.type == expected_type)
        tx_res = await session.execute(tx_stmt)
        tx_rows = tx_res.scalars().all()
        for tx in tx_rows:
            tx_type = (tx.type or "").lower()
            if tx_type not in {"expense", "income"} or not tx.category_id:
                continue
            weighted_counts[(tx_type, int(tx.category_id))] += 2.0
            verified_count += 1

        bench_stmt = (
            select(CategoryBenchmarkItem)
            .where(
                CategoryBenchmarkItem.expected_category_id.is_not(None),
                CategoryBenchmarkItem.expected_type.in_(["expense", "income"]),
                CategoryBenchmarkItem.description.ilike(f"%{keyword}%"),
            )
            .order_by(CategoryBenchmarkItem.id.desc())
            .limit(300)
        )
        if expected_type:
            bench_stmt = bench_stmt.where(CategoryBenchmarkItem.expected_type == expected_type)
        bench_res = await session.execute(bench_stmt)
        bench_rows = bench_res.scalars().all()
        for row in bench_rows:
            row_type = (row.expected_type or "").lower()
            if row_type not in {"expense", "income"} or not row.expected_category_id:
                continue
            weighted_counts[(row_type, int(row.expected_category_id))] += 1.0
            benchmark_count += 1

        if not weighted_counts:
            return None

        (top_type, top_cat), top_weight = weighted_counts.most_common(1)[0]
        total_weight = sum(weighted_counts.values())
        ratio = top_weight / max(1.0, total_weight)
        if top_weight < 3.0 or ratio < 0.68:
            return None

        conf = min(0.98, 0.84 + (ratio * 0.10) + (min(total_weight, 12.0) * 0.003))
        return {
            "type": top_type,
            "category_id": top_cat,
            "confidence": conf,
            "reasoning": (
                f"Merchant category precedent ({keyword}): "
                f"consensus ratio {ratio:.2f} from verified={verified_count}, benchmark={benchmark_count}."
            ),
        }

    def _parse_json_payload(self, content):
        try:
            import json
            cleaned = content.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        data = {}
        id_match = re.search(r'["\']id["\']:\s*(\d+|null|None)', content, re.IGNORECASE)
        conf_match = re.search(r'["\']confidence["\']:\s*([0-1]?\.?\d+)', content)
        type_match = re.search(r'["\']type["\']:\s*["\'](expense|income|transfer)["\']', content, re.IGNORECASE)
        reason_match = re.search(r'["\']reasoning["\']:\s*["\'](.*?)["\']', content, re.DOTALL)

        if id_match:
            raw_id = id_match.group(1)
            if raw_id.lower() not in ['null', 'none']:
                data["id"] = int(raw_id)
            else:
                data["id"] = None
        if conf_match:
            data["confidence"] = float(conf_match.group(1))
        if type_match:
            data["type"] = type_match.group(1).lower()
        if reason_match:
            data["reasoning"] = reason_match.group(1).strip()
        return data if data else None

    async def _chat_json_with_repair(self, prompt):
        content = await self._chat_once(prompt)
        data = self._parse_json_payload(content)
        if data is not None:
            return data, content

        repair_prompt = f"""
The following response is malformed. Convert it to strict JSON only.
Required keys: id (integer or null), type ("expense"|"income"|"transfer"), confidence (0.0-1.0), reasoning (string).
Text:
{content}
"""
        repaired_content = await self._chat_once(repair_prompt)
        repaired_data = self._parse_json_payload(repaired_content)
        return repaired_data, repaired_content

    def _parse_candidates_payload(self, content):
        try:
            import json
            cleaned = content.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if not match:
                return None
            payload = json.loads(match.group())
            raw_candidates = payload.get("candidates")
            if not isinstance(raw_candidates, list):
                return None
            return payload
        except Exception:
            return None

    async def suggest_category_candidates(
        self,
        description,
        session,
        min_candidates=3,
        extra_instruction=None,
        expected_type=None,
        amount_hint=None,
    ):
        """
        Suggest multiple candidate categories and types for a transaction.
        Returns list of dicts with keys: id, type, confidence, reasoning.
        """
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        if not categories:
            return []

        cat_by_id = {c.id: c for c in categories}
        expected_type = (expected_type or "").lower().strip()
        if expected_type not in {"expense", "income"}:
            expected_type = None
        eligible_categories = [c for c in categories if not expected_type or c.type == expected_type]
        eligible_by_id = {c.id: c for c in eligible_categories}

        # Deterministic fast-path:
        # if exact verified precedent exists with a single unanimous category/type,
        # return that as top candidate to avoid stochastic drift on repeated descriptions.
        try:
            exact_stmt = (
                select(Transaction)
                .where(
                    Transaction.description.ilike(description.strip()),
                    Transaction.is_verified.is_(True),
                    Transaction.category_id.is_not(None),
                )
                .order_by(Transaction.date.desc())
                .limit(20)
            )
            exact_res = await session.execute(exact_stmt)
            exact_rows = exact_res.scalars().all()
            if exact_rows:
                pairs = [(tx.category_id, (tx.type or "").lower()) for tx in exact_rows if tx.category_id]
                if pairs:
                    pair_counts = Counter(pairs)
                    (top_cat_id, top_type), top_count = pair_counts.most_common(1)[0]
                    unanimous = len(pair_counts) == 1
                    if unanimous and top_cat_id in cat_by_id:
                        if not expected_type or top_type == expected_type:
                            normalized = [
                                {
                                    "id": int(top_cat_id),
                                    "type": top_type if top_type in {"expense", "income"} else cat_by_id[top_cat_id].type,
                                    "confidence": 0.96,
                                    "reasoning": "Exact verified precedent match in transaction history.",
                                }
                            ]
                            used = {int(top_cat_id)}
                            target_type = normalized[0]["type"]
                            for c in sorted(eligible_categories, key=lambda x: (x.parent_name or "", x.name)):
                                if c.id in used:
                                    continue
                                if target_type in {"expense", "income"} and c.type != target_type:
                                    continue
                                normalized.append(
                                    {
                                        "id": c.id,
                                        "type": c.type,
                                        "confidence": 0.2,
                                        "reasoning": "Fallback candidate.",
                                    }
                                )
                                used.add(c.id)
                                if len(normalized) >= max(3, int(min_candidates)):
                                    break
                            return normalized
        except Exception:
            pass

        keyword_resolver = KeywordResolver()
        resolved_keyword = await keyword_resolver.resolve(description, session)
        search_term = resolved_keyword.keyword
        history_str = "None"

        profile_stmt = (
            select(AICategoryUnderstanding, Category)
            .join(Category, Category.id == AICategoryUnderstanding.category_id)
            .order_by(Category.type.asc(), Category.parent_name.asc(), Category.name.asc())
        )
        profile_res = await session.execute(profile_stmt)
        profile_rows = profile_res.all()

        shortlist_target = min(len(eligible_categories), max(12, int(min_candidates) * 6, 24))
        shortlisted_ids = []
        shortlisted_set = set()

        def _add_shortlisted(cid):
            if cid in eligible_by_id and cid not in shortlisted_set:
                shortlisted_ids.append(cid)
                shortlisted_set.add(cid)

        similar_verified_rows = []
        if len(search_term) > 2 and resolved_keyword.confidence >= 0.35:
            similar_stmt = (
                select(Transaction)
                .where(
                    Transaction.description.ilike(f"%{search_term}%"),
                    Transaction.category_id.is_not(None),
                    Transaction.is_verified.is_(True),
                )
                .order_by(Transaction.date.desc())
                .limit(120)
            )
            if expected_type:
                similar_stmt = similar_stmt.where(Transaction.type == expected_type)
            similar_res = await session.execute(similar_stmt)
            similar_verified_rows = similar_res.scalars().all()

        if similar_verified_rows:
            pair_counts = Counter(
                (int(tx.category_id), (tx.type or "").lower())
                for tx in similar_verified_rows
                if tx.category_id and (tx.type or "").lower() in {"expense", "income"}
            )
            for (cat_id, _ctype), _count in pair_counts.most_common(shortlist_target):
                _add_shortlisted(cat_id)

        keyword_tokens = [t for t in str(search_term or "").upper().split() if len(t) >= 4][:3]
        if keyword_tokens:
            for prof, cat in profile_rows:
                if cat.id not in eligible_by_id:
                    continue
                profile_blob = f"{prof.understanding or ''} {prof.sample_transactions_json or ''}".upper()
                if any(tok in profile_blob for tok in keyword_tokens):
                    _add_shortlisted(cat.id)
                    if len(shortlisted_ids) >= shortlist_target:
                        break

        for c in sorted(eligible_categories, key=lambda x: (x.parent_name or "", x.name)):
            if len(shortlisted_ids) >= shortlist_target:
                break
            _add_shortlisted(c.id)

        prompt_categories = [eligible_by_id[cid] for cid in shortlisted_ids] if shortlisted_ids else list(eligible_categories)
        prompt_category_ids = {c.id for c in prompt_categories}
        cat_lines = []
        for c in sorted(prompt_categories, key=lambda x: (x.parent_name or "", x.name)):
            parent = c.parent_name if c.parent_name else "No Parent"
            cat_lines.append(f"ID {c.id}: {parent} > {c.name} ({c.type})")
        cat_str = "\n".join(cat_lines)

        if len(search_term) > 2 and resolved_keyword.confidence >= 0.35:
            history_stmt = (
                select(Transaction, AIMemory)
                .outerjoin(AIMemory, Transaction.id == AIMemory.transaction_id)
                .where(
                    Transaction.description.ilike(f"%{search_term}%"),
                    Transaction.category_id.is_not(None),
                    Transaction.is_verified.is_(True),
                )
                .order_by(Transaction.date.desc())
                .limit(8)
            )
            if expected_type:
                history_stmt = history_stmt.where(Transaction.type == expected_type)

            history_res = await session.execute(history_stmt)
            history_rows = history_res.all()

            if history_rows:
                history_lines = []
                for tx, mem in history_rows:
                    cat_obj = cat_by_id.get(tx.category_id)
                    if cat_obj:
                        cat_name = f"{cat_obj.parent_name or 'Uncategorized'} > {cat_obj.name} [{cat_obj.type}]"
                    else:
                        cat_name = str(tx.category_id)

                    reflection_note = ""
                    if mem and mem.reflection:
                        reflection_note = f"\n  - LEARNING/REFLECTION: {mem.reflection}"

                    history_lines.append(
                        f"- '{tx.description}' -> {cat_name} ({tx.type}) [USER VERIFIED]{reflection_note}"
                    )

                history_str = "\n".join(history_lines)

        profiles_str = "None"
        if profile_rows:
            lines = []
            for p, c in profile_rows:
                if c.id not in prompt_category_ids:
                    continue
                lines.append(
                    f"- ID {c.id}: {(c.parent_name or 'Uncategorized')} > {c.name} [{c.type}] :: {p.understanding}"
                )
            if lines:
                profiles_str = "\n".join(lines)

        rule_stmt = select(AIGlobalMemory).where(AIGlobalMemory.is_active.is_(True)).order_by(AIGlobalMemory.created_at.desc()).limit(50)
        rule_res = await session.execute(rule_stmt)
        global_rules = rule_res.scalars().all()
        global_rules_list = [r.instruction for r in global_rules]
        global_rules_str = "None"
        if global_rules:
            global_rules_str = "\n".join([f"- {rule}" for rule in global_rules_list])
        if extra_instruction and extra_instruction not in global_rules_list:
            if global_rules_str == "None":
                global_rules_str = f"- {extra_instruction}"
            else:
                global_rules_str += f"\n- {extra_instruction}"

        merchant_hint = resolved_keyword.keyword
        merchant_hint_confidence = resolved_keyword.confidence
        merchant_hint_source = resolved_keyword.source
        clean_desc = self._clean_description(description)
        amount_hint_text = "unknown"
        if amount_hint is not None:
            try:
                amount_hint_text = f"{float(amount_hint):.2f}"
            except Exception:
                amount_hint_text = str(amount_hint)
        search_query = (
            self._clean_description(merchant_hint)
            if merchant_hint and merchant_hint != "UNKNOWN" and merchant_hint_confidence >= 0.35
            else clean_desc
        )
        search_results = self._run_web_search(search_query, max_results=2)
        search_context = self._format_search_results(search_results)

        prompt = f"""
You are a financial assistant.
Categorize this transaction and provide multiple plausible options.
Transaction: "{description}"
cleaned_description: '{clean_desc}'
merchant_hint: '{merchant_hint}'
merchant_hint_confidence: '{merchant_hint_confidence:.2f}'
merchant_hint_source: '{merchant_hint_source}'
expected_type: '{expected_type or "unknown"}'
amount_hint: '{amount_hint_text}'

Web Search Context:
{search_context}

Available Categories (List):
{cat_str}

Memory Bank (Similar Past Transactions & Reflections):
{history_str}

Category Understanding Memory (stored category intent profiles):
{profiles_str}

Global User Rulebook (persistent coaching):
{global_rules_str}

Rules:
- If you see a "LEARNING/REFLECTION", you MUST apply that logic.
- If you see a category understanding profile for a category, treat it as a strong prior for that category.
- The category decision must be based on merchant/payee intent, NOT location.
- Location can be ignored if present; do not use it to decide category.
- Ignore banking noise like ATM/VISA/EFTPOS/card suffixes and legal prefixes.
- You MUST choose IDs from the provided category list only.
- Do not invent categories.
- Return at least {max(3, int(min_candidates))} unique candidates, ranked best first.
- Prefer non-transfer category candidates unless the transaction is clearly an internal transfer.
- If expected_type is "expense" or "income", all candidates MUST use that same type.
- Treat merchant_hint as primary merchant/payee signal. Do NOT use suburb/city/country/location tails as merchant names.
- Use amount_hint sign/size only as a weak tiebreaker.

Return JSON object only:
{{
  "candidates": [
    {{"id": 123, "type": "expense", "confidence": 0.82, "reasoning": "short reason"}},
    {{"id": 456, "type": "expense", "confidence": 0.61, "reasoning": "short reason"}}
  ]
}}
JSON ONLY.
"""
        try:
            content = await self._chat_once(prompt)
            data = self._parse_candidates_payload(content)
            if data is None:
                repair_prompt = f"""
Convert the following output to strict JSON only.
Required format:
{{
  "candidates": [
    {{"id": <int>, "type": "expense|income|transfer", "confidence": <0.0-1.0>, "reasoning": "<string>"}}
  ]
}}
At least {max(3, int(min_candidates))} unique candidate entries.
Text:
{content}
"""
                repaired = await self._chat_once(repair_prompt)
                data = self._parse_candidates_payload(repaired)

            normalized = []
            seen = set()
            for item in (data or {}).get("candidates", []):
                if not isinstance(item, dict):
                    continue
                raw_type = str(item.get("type", "expense")).lower()
                ctype = raw_type if raw_type in {"expense", "income", "transfer"} else "expense"
                if expected_type and ctype != expected_type:
                    continue

                raw_id = item.get("id")
                cid = None
                try:
                    if raw_id is not None:
                        cid = int(raw_id)
                except Exception:
                    cid = None

                if ctype == "transfer":
                    continue
                if cid is None or cid not in eligible_by_id:
                    continue
                if cat_by_id[cid].type != ctype:
                    continue

                key = (ctype, cid)
                if key in seen:
                    continue
                seen.add(key)

                try:
                    conf = float(item.get("confidence", 0.0))
                except Exception:
                    conf = 0.0
                conf = max(0.0, min(1.0, conf))
                reason = str(item.get("reasoning", "Possible match."))
                normalized.append({
                    "id": cid,
                    "type": ctype,
                    "confidence": conf,
                    "reasoning": reason,
                })

            if len(normalized) < max(3, int(min_candidates)):
                used = {c["id"] for c in normalized}
                for c in sorted(prompt_categories, key=lambda x: (x.parent_name or "", x.name)):
                    if expected_type and c.type != expected_type:
                        continue
                    if c.id in used:
                        continue
                    normalized.append({
                        "id": c.id,
                        "type": c.type,
                        "confidence": 0.2,
                        "reasoning": "Fallback candidate.",
                    })
                    used.add(c.id)
                    if len(normalized) >= max(3, int(min_candidates)):
                        break

            if len(normalized) < max(3, int(min_candidates)):
                used = {c["id"] for c in normalized}
                for c in sorted(eligible_categories, key=lambda x: (x.parent_name or "", x.name)):
                    if c.id in used:
                        continue
                    normalized.append(
                        {
                            "id": c.id,
                            "type": c.type,
                            "confidence": 0.15,
                            "reasoning": "Global fallback candidate.",
                        }
                    )
                    used.add(c.id)
                    if len(normalized) >= max(3, int(min_candidates)):
                        break

            return sorted(normalized, key=lambda x: x["confidence"], reverse=True)
        except Exception as e:
            print(f"AI Error: {e}")
            return []

    async def suggest_category(self, description, session, extra_instruction=None, expected_type=None, amount_hint=None):
        """
        Suggests category and type for the transaction.
        Returns (category_id, confidence, reasoning, type)
        """
        try:
            normalized_expected_type = (expected_type or "").strip().lower()
            if normalized_expected_type not in {"expense", "income"}:
                normalized_expected_type = None

            precedent = await self._get_exact_verified_precedent(description, session)
            if precedent:
                if precedent["type"] == "transfer":
                    return None, precedent["confidence"], precedent["reasoning"], "transfer"
                return (
                    int(precedent["category_id"]),
                    precedent["confidence"],
                    precedent["reasoning"],
                    precedent["type"],
                )

            if not normalized_expected_type and self._looks_like_probable_transfer(description):
                return (
                    None,
                    0.90,
                    "Probable transfer rails detected (RTP/Wise Transfer/OSKO style marker).",
                    "transfer",
                )

            merchant_precedent = await self._get_merchant_category_precedent(
                description,
                session,
                expected_type=normalized_expected_type,
            )
            if merchant_precedent:
                return (
                    int(merchant_precedent["category_id"]),
                    merchant_precedent["confidence"],
                    merchant_precedent["reasoning"],
                    merchant_precedent["type"],
                )

            keyword_precedent = await self._get_keyword_verified_precedent(
                description,
                session,
                expected_type=normalized_expected_type,
                amount_hint=amount_hint,
            )
            if keyword_precedent:
                return (
                    int(keyword_precedent["category_id"]),
                    keyword_precedent["confidence"],
                    keyword_precedent["reasoning"],
                    keyword_precedent["type"],
                )

            if self._is_internal_transfer_text(description):
                return (
                    None,
                    0.92,
                    "Internal transfer cues detected (joint account/internet banking pattern).",
                    "transfer",
                )

            candidates = await self.suggest_category_candidates(
                description,
                session,
                min_candidates=3,
                extra_instruction=extra_instruction,
                expected_type=normalized_expected_type,
                amount_hint=amount_hint,
            )
            if not candidates:
                return None, 0.0, "Unable to produce category suggestions.", "expense"
            top = candidates[0]
            return top["id"], top["confidence"], top["reasoning"], top["type"]
        except Exception as e:
            print(f"AI Error: {e}")
            return None, 0.0, f"Error: {e}", "expense"

    async def discuss_transaction(
        self,
        tx_data,
        current_type,
        current_cat_id,
        current_reasoning,
        session,
        user_message,
        conversation_history=None,
        rag_pipeline=None, # Injected LocalLLMPipeline instance
        web_search_query=None,
    ):
        """
        Conversational assistant for discussing a single in-review transaction.
        """
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        cat_by_id = {c.id: c for c in categories}
        cat_lines = []
        for c in sorted(categories, key=lambda x: (x.parent_name or "", x.name)):
            cat_lines.append(f"ID {c.id}: {(c.parent_name or 'No Parent')} > {c.name} ({c.type})")
        categories_text = "\n".join(cat_lines) if cat_lines else "No categories available."

        if current_type == "transfer" and current_cat_id is None:
            current_label = "(Transfer) > (Transfer)"
        elif current_cat_id in cat_by_id:
            cat = cat_by_id[current_cat_id]
            current_label = f"{cat.parent_name or 'Uncategorized'} > {cat.name}"
        else:
            current_label = "Uncategorized > Uncategorized"

        web_context = "None"
        if web_search_query:
            web_context = self._format_search_results(self._run_web_search(web_search_query, max_results=3))

        history_text = "None"
        if conversation_history:
            lines = []
            for msg in conversation_history[-12:]:
                role = msg.get("role", "user").upper()
                content = msg.get("content", "")
                lines.append(f"{role}: {content}")
            history_text = "\n".join(lines)

        # RAG Retrieval if pipeline provided
        rag_context = "No relevant past transactions found."
        if rag_pipeline:
            # query based on description + user message
            query = f"{tx_data.get('description')} {user_message}"
            hits = await rag_pipeline.retrieve(session, query, top_k=5)
            if hits:
                rag_context = "\n".join([f"- {h.content} (Score: {h.score:.2f})" for h in hits])

        prompt = f"""
You are assisting a user in categorizing a transaction.
Transaction:
- Date: {tx_data.get("date")}
- Amount: {tx_data.get("amount")}
- Description: {tx_data.get("description")}

Current Decision:
- Type: {current_type}
- Category: {current_label}
- Reasoning: {current_reasoning}

Conversation History:
{history_text}

Relevant Past Information (RAG):
{rag_context}

Available Categories:
{categories_text}

User Input: "{user_message}"

Instructions:
- Answer the user's question or concern directly.
- If the user corrects you, ask "Why?" to understand the pattern (unless obvious).
- Use the RAG context to support your answer (e.g., "In the past, you categorized similar items as...").
- Be concise and helpful.
"""
        try:
            return await self._chat_once(prompt)
        except Exception as e:
            return f"I could not complete that discussion step: {e}"

    async def summarize_review_conversation(self, tx_description, conversation_history):
        """
        Summarize a review discussion into compact instructions for re-categorization.
        """
        if not conversation_history:
            return ""

        lines = []
        for msg in conversation_history[-20:]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        convo_text = "\n".join(lines)

        prompt = f"""
Summarize the following transaction-review conversation into concise categorization guidance.
The guidance will be fed into a categorizer as extra instruction.
Keep it <= 4 bullet points and include only actionable rules or conclusions.
If no strong conclusion, state uncertainty briefly.

Transaction description: {tx_description}
Conversation:
{convo_text}
"""
        try:
            return await self._chat_once(prompt)
        except Exception:
            return ""

    async def generate_reflection(self, description, old_category, new_category, previous_reasoning):
        """
        Asks AI to reflect on why it was wrong and what to learn.
        """
        prompt = f"""
I made a mistake in categorizing: '{description}'
I thought it was: {old_category}
Reasoning was: {previous_reasoning}

The USER corrected it to: {new_category}

Task:
Write a short "Reflection" rule for the Memory Bank.
Example: "When I see 'Shell', if amount is positive it is Refund, otherwise Fuel."
Example: " 'Uber' is usually 'Transport', but 'Uber Eats' is 'Food'."
Keep it concise (1 sentence).

Reflection:
"""
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content'].strip()
        except Exception:
            return "User corrected category."

    async def generate_correctness_reflection(self, description, category_label, previous_reasoning):
        """
        Asks AI to explain why the current decision is correct for future reuse.
        """
        prompt = f"""
Transaction: '{description}'
Current category: {category_label}
Current reasoning: {previous_reasoning}

Task:
Write a short "Reflection" rule for the Memory Bank explaining why this categorization is correct.
Keep it concise (1 sentence), reusable, and focused on merchant/payee intent.

Reflection:
"""
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content'].strip()
        except Exception:
            return "Current category verified by user as correct."
