import ollama
import re
from sqlalchemy import select
from src.database import Category, Transaction, AIMemory

class CategorizerAI:
    def __init__(self, model="llama3.2:3b"):
        """
        Initialize with the Ollama model.
        Ensure 'ollama serve' is running and the model is pulled.
        """
        self.model = model
        self.client = ollama.AsyncClient()

    async def suggest_category(self, description, session):
        """
        Suggests category and type for the transaction.
        Returns (category_id, confidence, reasoning, type)
        """
        # 1. Fetch available categories
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        if not categories:
            return None, 0.0, "No categories found.", "expense"
            
        cat_lines = [f"{c.id}: {c.parent_name} > {c.name} ({c.type})" for c in categories]
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

        # 3. Web Search Context
        search_context = "No information found."
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(description, max_results=2))
                if results:
                    search_context = "\n".join([f"- {r['param1']}: {r['body']}" for r in results])
        except Exception as e:
            search_context = f"Web search failed: {e}"

        # 4. Construct Prompt
        prompt = f"""
You are a financial assistant.
Categorize this transaction: '{description}'

Web Search Context:
{search_context}

Available Categories:
{cat_str}

Memory Bank (Similar Past Transactions & Reflections):
{history_str}

Reflections instructions:
- If you see a "LEARNING/REFLECTION", you MUST apply that logic.
- "Transfer" usually means movement between accounts (not an expense).
- "Salary" is Income.

Task:
Return a JSON object with:
- "id": category ID (int) OR null if unsure/new.
- "confidence": score (0.0 - 1.0)
- "type": "expense", "income", or "transfer"
- "reasoning": Explanation citing memory/reflection or web search.

JSON ONLY.
"""
        
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            content = response['message']['content'].strip()
            
            # JSON Parsing with fallback
            data = {}
            try:
                import json
                content = content.replace("```json", "").replace("```", "").strip()
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    raise ValueError("No JSON block")
            except Exception:
                # Regex Fallback
                id_match = re.search(r'["\']id["\']:\s*(\d+|null|None)', content, re.IGNORECASE)
                conf_match = re.search(r'["\']confidence["\']:\s*([0-1]?\.?\d+)', content)
                type_match = re.search(r'["\']type["\']:\s*["\'](expense|income|transfer)["\']', content, re.IGNORECASE)
                reason_match = re.search(r'["\']reasoning["\']:\s*["\'](.*?)["\']', content)
                
                if id_match and id_match.group(1).lower() not in ['null', 'none']:
                    data["id"] = int(id_match.group(1))
                if conf_match:
                    data["confidence"] = float(conf_match.group(1))
                if type_match:
                    data["type"] = type_match.group(1).lower()
                if reason_match:
                    data["reasoning"] = reason_match.group(1)

            suggested_id = data.get("id")
            if suggested_id is not None:
                suggested_id = int(suggested_id)
                
            confidence = float(data.get("confidence", 0.0))
            reasoning = data.get("reasoning", "No reasoning.")
            tx_type = data.get("type", "expense")
            
            # Validation
            if suggested_id:
                valid_ids = {c.id for c in categories}
                if suggested_id not in valid_ids:
                    return None, 0.0, f"Invalid ID {suggested_id}", tx_type
            
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
