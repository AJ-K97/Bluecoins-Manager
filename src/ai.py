import ollama
import re
from sqlalchemy import select
from src.database import Category, Transaction, AIMemory, AIGlobalMemory, AICategoryUnderstanding
from src.patterns import extract_pattern_key

class CategorizerAI:
    def __init__(self, model="llama3.1:8b"):
        """
        Initialize with the Ollama model.
        Ensure 'ollama serve' is running and the model is pulled.
        """
        self.model = model
        self.client = ollama.AsyncClient()

    async def _chat_once(self, prompt):
        response = await self.client.chat(model=self.model, messages=[
            {'role': 'user', 'content': prompt}
        ])
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
        cat_lines = []
        for c in sorted(categories, key=lambda x: (x.parent_name or "", x.name)):
            parent = c.parent_name if c.parent_name else "No Parent"
            cat_lines.append(f"ID {c.id}: {parent} > {c.name} ({c.type})")

        cat_str = "\n".join(cat_lines)

        search_term = extract_pattern_key(description)
        history_str = "None"

        if len(search_term) > 2:
            stmt = select(Transaction, AIMemory).outerjoin(AIMemory, Transaction.id == AIMemory.transaction_id).where(
                Transaction.description.ilike(f"%{search_term}%"),
                Transaction.category_id.is_not(None)
            ).order_by(Transaction.date.desc()).limit(5)

            res = await session.execute(stmt)
            rows = res.all()

            if rows:
                history_lines = []
                for tx, mem in rows:
                    cat_obj = next((c for c in categories if c.id == tx.category_id), None)
                    if cat_obj:
                        cat_name = f"{cat_obj.parent_name or 'Uncategorized'} > {cat_obj.name} [{cat_obj.type}]"
                    else:
                        cat_name = str(tx.category_id)

                    reflection_note = ""
                    if mem and mem.reflection:
                        reflection_note = f"\n  - LEARNING/REFLECTION: {mem.reflection}"

                    user_tag = "[USER VERIFIED]" if tx.is_verified else "[AI PREDICTION]"
                    history_lines.append(f"- '{tx.description}' -> {cat_name} ({tx.type}) {user_tag}{reflection_note}")

                history_str = "\n".join(history_lines)

        profile_stmt = (
            select(AICategoryUnderstanding, Category)
            .join(Category, Category.id == AICategoryUnderstanding.category_id)
            .order_by(Category.type.asc(), Category.parent_name.asc(), Category.name.asc())
        )
        profile_res = await session.execute(profile_stmt)
        profile_rows = profile_res.all()
        profiles_str = "None"
        if profile_rows:
            lines = []
            for p, c in profile_rows:
                lines.append(
                    f"- ID {c.id}: {(c.parent_name or 'Uncategorized')} > {c.name} [{c.type}] :: {p.understanding}"
                )
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

        expected_type = (expected_type or "").lower().strip()
        if expected_type not in {"expense", "income"}:
            expected_type = None

        merchant_hint = extract_pattern_key(description)
        clean_desc = self._clean_description(description)
        search_query = self._clean_description(merchant_hint) if merchant_hint and merchant_hint != "UNKNOWN" else clean_desc
        search_results = self._run_web_search(search_query, max_results=2)
        search_context = self._format_search_results(search_results)

        prompt = f"""
You are a financial assistant.
Categorize this transaction and provide multiple plausible options.
Transaction: "{description}"
cleaned_description: '{clean_desc}'
merchant_hint: '{merchant_hint}'
expected_type: '{expected_type or "unknown"}'

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
                if cid is None or cid not in cat_by_id:
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
                for c in sorted(categories, key=lambda x: (x.parent_name or "", x.name)):
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

            return sorted(normalized, key=lambda x: x["confidence"], reverse=True)
        except Exception as e:
            print(f"AI Error: {e}")
            return []

    async def suggest_category(self, description, session, extra_instruction=None, expected_type=None):
        """
        Suggests category and type for the transaction.
        Returns (category_id, confidence, reasoning, type)
        """
        try:
            candidates = await self.suggest_category_candidates(
                description,
                session,
                min_candidates=3,
                extra_instruction=extra_instruction,
                expected_type=expected_type,
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
        web_search_query=None
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

        prompt = f"""
You are helping a user review one bank transaction.
Do not output JSON. Give a clear conversational answer.
If asked to search, use provided web search context and cite uncertain points.
Focus on WHY the current categorization was chosen, possible alternatives, and what evidence would change it.

Transaction:
- Date: {tx_data.get("date")}
- Amount: {tx_data.get("amount")}
- Description: {tx_data.get("description")}

Current model decision:
- Type: {current_type}
- Category: {current_label}
- Reasoning: {current_reasoning or "No reasoning yet."}

Available categories:
{categories_text}

Conversation so far:
{history_text}

Web search context (if requested):
{web_context}

User message:
{user_message}
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
