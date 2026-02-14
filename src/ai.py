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

        # 3. Construct Prompt
        prompt = f"""
You are a financial assistant.
Categorize this transaction: '{description}'

Available Categories:
{cat_str}

Similar Past Transactions:
{history_str}

Task:
Return ONLY the ID of the best matching category from the list above.
If fuzzy match with past transaction is strong, use that.
If no good match, default to a general category ID or return 0.
Reply with just the number.
"""
        
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            content = response['message']['content'].strip()
            
            # Extract first number
            match = re.search(r'\d+', content)
            if match:
                return int(match.group())
            return None
            
        except Exception as e:
            print(f"AI Suggestion Error: {e}")
            return None
