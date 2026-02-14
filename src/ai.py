import ollama
import re
from sqlalchemy import select
from src.database import Category, Transaction, AIMemory

class CategorizerAI:
    def __init__(self, model="llama3.1:8b"):
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

        # 3. Web Search Context
        # Clean description for better search/AI context
        # Remove dates, times, long numeric codes using approx regex
        # 3. Web Search Context
        # Clean description for better search/AI context
        # Remove dates (DDMMMYY, DD/MM/YYYY etc approx)
        clean_desc = re.sub(r'\d{2}[A-Z]{3}\d{2}', '', description) # 28JAN26
        # Remove times
        clean_desc = re.sub(r'\d{2}:\d{2}:\d{2}', '', clean_desc) # 23:30:46
        
        # Aggressive Cleaning: Remove card info, long codes, banking noise
        # 4-digit numbers (often card ending)
        clean_desc = re.sub(r'\b\d{4}\b', '', clean_desc)
        # Long alphanumeric codes (6+ chars)
        clean_desc = re.sub(r'\b[A-Z0-9]{6,}\b', '', clean_desc)
        # Specific banking keywords and variations
        clean_desc = re.sub(r'\b(VISA|AUD|ATMA\d*|EFTPOS|DEBIT|CREDIT)\b', '', clean_desc, flags=re.IGNORECASE)
        
        clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
        
        search_context = "No information found."
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(clean_desc, max_results=2))
                if results:
                    search_context = "\n".join([f"- {r['param1']}: {r['body']}" for r in results])
        except Exception as e:
            search_context = f"Web search failed: {e}"

        # 4. Construct Prompt
        prompt = f"""
You are a financial assistant.
Categorize this transaction: '{description}'
cleaned_description: '{clean_desc}'

Web Search Context:
{search_context}

Available Categories (List):
{cat_str}

Memory Bank (Similar Past Transactions & Reflections):
{history_str}

General Rules & ID hints:
- "Salary" -> Income > Salary (Type: income)
- "Transfer" -> Transfer > Transfer (Type: transfer)

Reflections instructions:
- If you see a "LEARNING/REFLECTION", you MUST apply that logic.
- Do NOT hallucinate "Water" or "Utilities" for ordinary shops.
- Use "Web Search Context" to identify the merchant's business type.
- Ignore "ATM", "VISA", "EFTPOS" keywords. Focus on the merchant.
- Ignore legal prefixes like "THE TRUSTEE FOR", "PTY LTD", "TRUST" when identifying the Payee. "THE TRUSTEE FOR BCF" -> Payee is "BCF".

Task:
1. Identify the **Payee** (Merchant/Person) and **Location** (if available) from the description.
2. Determine if it is a Transfer (e.g. "Transfer", "Internal Transfer", "Osko"). 
   - **CRITICAL**: A transaction is NOT a transfer if it is a purchase from a business.
   - Presence of a **Location** (e.g. Canning Vale) does NOT make it a Transfer.
   - If the Payee is a known entity/brand, it is likely a PURCHASE.
3. Determine the category based on the Payee/Type.
4. Return a JSON object with:
- "payee": The extracted merchant/payee name.
- "location": The extracted location (or null).
- "reasoning": Concise explanation. Mention why you ruled out others if unsure.
- "id": The EXACT Category ID from the list above. 
    - Verify the ID exists in the specific "Available Categories" list provided.
    - If it is a Transfer, use the Transfer category ID (usually 31 or similar).
    - If you think it is "App/Subscription", look for ID under "Entertainment".
    - If you think it is "Eating Out" or "Food", look for "Food" under "Entertainment".
- "confidence": score (0.0 - 1.0)
- "type": "expense", "income", or "transfer"

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
            if isinstance(reasoning, (dict, list)):
                import json # Ensure json is available
                reasoning = json.dumps(reasoning)
            else:
                reasoning = str(reasoning)
                
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
