import json
import re
import ollama

from src.ai_config import get_ollama_client

class IntentAI:
    def __init__(self, model="llama3.1:8b"):
        self.model = model
        self.client = get_ollama_client()

    async def classify(self, text: str):
        """
        Classifies the user's natural language input into a specific intent and extracts entities.
        """
        from src.persona import BluecoinsPersona
        prompt = f"""
{BluecoinsPersona.get_intent_prompt()}

User Message: "{text}"
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
