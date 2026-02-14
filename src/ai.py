import ollama
import re
from sqlalchemy import select
from src.database import Category, Transaction

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
        Suggests a category ID for the given transaction description.
        Returns Integery category_id or None.
        """
        # 1. Fetch available categories
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        if not categories:
            return None
            
        # Format: "ID: Parent > Name (Type)"
        cat_lines = [f"{c.id}: {c.parent_name} > {c.name} ({c.type})" for c in categories]
        cat_str = "\n".join(cat_lines)
        
        # 2. Fetch history (Simple similarity search)
        # Search for transactions starting with the same first word (often Merchant name)
        words = description.split()
        search_term = words[0] if words else ""
        history_str = "None"
        
        if len(search_term) > 2:
            # Get last 5 similar transactions that have a category
            stmt = select(Transaction).where(
                Transaction.description.ilike(f"{search_term}%"),
                Transaction.category_id.is_not(None)
            ).order_by(Transaction.date.desc()).limit(5)
            
            res = await session.execute(stmt)
            txs = res.scalars().all()
            
            if txs:
                history_lines = []
                for t in txs:
                    # We need the category name for context, so we might need eager load or just show ID
                    # AI can map ID if we provided the list above.
                    history_lines.append(f"- '{t.description}' -> Category ID {t.category_id}")
                history_str = "\n".join(history_lines)

        # 3. Web Search Context
        search_context = "No information found."
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                # Search for the description (usually Payee)
                # Cleaning description might help (remove dates/numbers if noisy)
                query = description
                results = list(ddgs.text(query, max_results=2))
                if results:
                    search_context = "\n".join([f"- {r['param1']}: {r['body']}" for r in results])
        except ImportError:
            search_context = "Web search module not installed."
        except Exception as e:
            search_context = f"Web search failed: {e}"

        # 4. Construct Prompt
        prompt = f"""
You are a financial assistant.
Categorize this transaction: '{description}'

Web Search Context (Background info about payee):
{search_context}

Available Categories:
{cat_str}

Similar Past Transactions:
{history_str}

Task:
Return ONLY the ID of the best matching category and a confidence score (0.0 to 1.0).
Format: "ID, Confidence" (e.g. "123, 0.95")
"""
        
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            content = response['message']['content'].strip()
            
            # Parsing "ID, Confidence"
            import re
            valid_ids = {c.id for c in categories}
            
            # Try to match: digits, then maybe comma, then float
            match = re.search(r'(\d+)\s*,\s*([0-1]?\.?\d+)', content)
            
            if match:
                suggested_id = int(match.group(1))
                confidence = float(match.group(2))
                if suggested_id in valid_ids:
                    return suggested_id, confidence
            
            # Fallback for just ID
            match_id = re.search(r'(\d+)', content)
            if match_id:
                 suggested_id = int(match_id.group(1))
                 if suggested_id in valid_ids:
                     return suggested_id, 0.5 # Default confidence if not provided
                     
            return None, 0.0
            
        except Exception as e:
            print(f"AI Suggestion Error: {e}")
            return None, 0.0
