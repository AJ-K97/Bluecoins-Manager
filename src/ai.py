import ollama
import re
from sqlalchemy import select
from src.database import Category, Transaction, AIMemory, AIGlobalMemory

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

    async def suggest_category(self, description, session, extra_instruction=None):
        """
        Suggests category and type for the transaction.
        Returns (category_id, confidence, reasoning, type)
        """
        # 1. Fetch available categories
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        if not categories:
            return None, 0.0, "No categories found.", "expense"

        cat_by_id = {c.id: c for c in categories}
        cat_lines = []
        for c in sorted(categories, key=lambda x: (x.parent_name or "", x.name)):
            parent = c.parent_name if c.parent_name else "No Parent"
            cat_lines.append(f"ID {c.id}: {parent} > {c.name} ({c.type})")

        cat_str = "\n".join(cat_lines)

        # 2. Fetch Memory (Reflections & Past Decisions)
        words = description.split()
        search_term = words[0] if words else ""
        history_str = "None"

        if len(search_term) > 2:
            # Join Transaction with AIMemory to get reflections
            stmt = select(Transaction, AIMemory).outerjoin(AIMemory, Transaction.id == AIMemory.transaction_id).where(
                Transaction.description.ilike(f"%{search_term}%"),
                Transaction.category_id.is_not(None)
            ).order_by(Transaction.date.desc()).limit(5)
            
            res = await session.execute(stmt)
            rows = res.all() # list of (Transaction, AIMemory) tuples
            
            if rows:
                history_lines = []
                for tx, mem in rows:
                    cat_name = next((c.name for c in categories if c.id == tx.category_id), str(tx.category_id))
                    
                    reflection_note = ""
                    if mem and mem.reflection:
                        reflection_note = f"\n  - LEARNING/REFLECTION: {mem.reflection}"
                    
                    # If verified by user, mark it
                    user_tag = "[USER VERIFIED]" if tx.is_verified else "[AI PREDICTION]"
                    
                    history_lines.append(f"- '{tx.description}' -> {cat_name} ({tx.type}) {user_tag}{reflection_note}")
                
                history_str = "\n".join(history_lines)

        # 2.5 Fetch Global User Coaching/Rules
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

        # 3. Web Search Context
        clean_desc = re.sub(r'\d{2}[A-Z]{3}\d{2}', '', description) # 28JAN26
        clean_desc = re.sub(r'\d{2}:\d{2}:\d{2}', '', clean_desc) # 23:30:46
        clean_desc = re.sub(r'\b\d{4}\b', '', clean_desc)
        clean_desc = re.sub(r'\b[A-Z0-9]{6,}\b', '', clean_desc)
        clean_desc = re.sub(r'\b(VISA|AUD|ATMA\d*|EFTPOS|DEBIT|CREDIT)\b', '', clean_desc, flags=re.IGNORECASE)
        clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()

        search_context = "No information found."
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(clean_desc, max_results=2))
                if results:
                    search_context = "\n".join([f"- {r.get('title', 'Unknown')}: {r.get('body', '')}" for r in results])
        except Exception as e:
            search_context = f"Web search failed: {e}"

        # 4. Construct Prompt
        prompt = f"""
You are a financial assistant.
Categorize this transaction: "{description}"
cleaned_description: '{clean_desc}'

Web Search Context:
{search_context}

Available Categories (List):
{cat_str}

Memory Bank (Similar Past Transactions & Reflections):
{history_str}

Global User Rulebook (persistent coaching):
{global_rules_str}

Rules:
- If you see a "LEARNING/REFLECTION", you MUST apply that logic.
- The category decision must be based on merchant/payee intent, NOT location.
- Location can be ignored if present; do not use it to decide category.
- Ignore banking noise like ATM/VISA/EFTPOS/card suffixes and legal prefixes.
- You MUST choose id from the provided category list only.
- If transaction is transfer/internal transfer/osko between accounts, set type to "transfer" and id to null.
- Do not invent categories.

Task:
Return JSON object only with:
- "id": exact category ID from list, or null for transfer.
- "type": "expense", "income", or "transfer"
- "confidence": score (0.0 - 1.0)
- "reasoning": concise reasoning

JSON ONLY.
"""

        try:
            data, _raw_content = await self._chat_json_with_repair(prompt)
            if data is None:
                return None, 0.0, "Unable to parse AI response.", "expense"

            suggested_id = data.get("id")
            if suggested_id is not None:
                suggested_id = int(suggested_id)

            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))

            reasoning = data.get("reasoning", "No reasoning.")
            reasoning = str(reasoning)

            tx_type = str(data.get("type", "expense")).lower()
            if tx_type not in {"expense", "income", "transfer"}:
                tx_type = "expense"

            if tx_type == "transfer":
                return None, confidence, reasoning, "transfer"

            if suggested_id is not None:
                if suggested_id not in cat_by_id:
                    return None, 0.0, f"{reasoning} [Invalid ID {suggested_id}]", tx_type

                cat = cat_by_id[suggested_id]
                if cat.type != tx_type:
                    return None, 0.0, f"{reasoning} [Type/category mismatch: {tx_type} vs {cat.type}]", tx_type

            return suggested_id, confidence, reasoning, tx_type

        except Exception as e:
            print(f"AI Error: {e}")
            return None, 0.0, f"Error: {e}", "expense"

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
