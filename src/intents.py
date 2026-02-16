import json
import re
import ollama

class IntentAI:
    def __init__(self, model="llama3.1:8b"):
        self.model = model
        self.client = ollama.AsyncClient()

    async def classify(self, text: str):
        """
        Classifies the user's natural language input into a specific intent and extracts entities.
        """
        prompt = f"""
You are an intent classifier for a personal finance bot (Bluecoins Manager).
Analyze the user message and return a JSON object with the detected intent and entities.

Intents:
- ADD_TRANSACTION: User wants to log a new expense or income.
- ADD_ACCOUNT: User wants to create a new bank/financial account.
- ADD_CATEGORY: User wants to create a new budget category.
- LIST_ACCOUNTS: User wants to see their accounts.
- LIST_CATEGORIES: User wants to see their budget structure.
- LIST_RULEBOOK: User wants to see AI knowledge or fine-tune examples.
- REVIEW_QUEUE: User wants to process pending transactions.
- MODIFY_TRANSACTION: User wants to edit a specific existing transaction.
- CHAT_QUERY: Default intent for general questions, reports, or advice.

Entities to extract:
- amount (float)
- description (string)
- name (string - for account or category)
- transaction_id (integer - for modifications)

User Message: "{text}"

Return JSON ONLY in this format:
{{
  "intent": "INTENT_NAME",
  "entities": {{
    "amount": null,
    "description": null,
    "name": null,
    "transaction_id": null
  }},
  "confidence": 0.0-1.0
}}
"""
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            content = response['message']['content'].strip()
            
            # Extract JSON from potential markdown blocks
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return data
            return {"intent": "CHAT_QUERY", "entities": {}, "confidence": 0}
        except Exception as e:
            print(f"IntentAI Error: {e}")
            return {"intent": "CHAT_QUERY", "entities": {}, "confidence": 0}
