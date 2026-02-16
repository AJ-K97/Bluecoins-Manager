
from typing import List, Any, Dict

class BluecoinsPersona:
    """
    Defines the persona and style for the Bluecoins Manager bot.
    """
    
    # Style Constants
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    MONEY = "💰"
    BANK = "🏦"
    TAG = "🏷️"
    CALENDAR = "📅"
    ROBOT = "🤖"
    SEARCH = "🔎"
    
    # Formats
    DATE_FMT = "%Y-%m-%d"

    @staticmethod
    def format_currency(amount: float) -> str:
        """Formats a float as a currency string (e.g., $1,234.56)."""
        return f"${amount:,.2f}"

    @staticmethod
    def format_sources(hits: List[Any]) -> str:
        """
        Formats a list of RetrievalHit objects into a Markdown source block.
        Expects hits to have .metadata dict with 'date', 'description', 'amount'.
        """
        if not hits:
            return ""

        lines = ["\n\n**Sources:**"]
        for i, hit in enumerate(hits, 1):
            meta = hit.metadata
            date = meta.get("date", "Unknown Date")
            desc = meta.get("description", "Unknown Transaction")
            amount = meta.get("amount", 0.0)
            
            # Try to shorten date to YYYY-MM-DD
            if "T" in date:
                date = date.split("T")[0]
            
            lines.append(f"{i}. {date} - {desc} (**{BluecoinsPersona.format_currency(amount)}**)")
        
        return "\n".join(lines)
    
    @staticmethod
    def _get_base_system_prompt() -> str:
        return (
            "You are **Bluecoins Steward**, an expert personal finance assistant.\n"
            "Your goal is to help the user understand their financial health using strict data grounding.\n\n"
            "**Persona Guidelines:**\n"
            "1. **Tone**: Professional, concise, data-driven, yet helpful and protective of the user's wealth.\n"
            "2. **Formatting**: Use Markdown. Bold key figures (e.g., **$50.00**). Use lists for multiple items.\n"
            "3. **Accuracy**: Only use provided context. If context is missing, explicitly state what is missing. **Never invents transactions.**\n"
            "4. **Style**: Use emojis sparingly to highlight key information (like 💰 for money, ⚠️ for warnings), but do not clutter the response.\n"
        )

    @staticmethod
    def get_chat_prompt(active_skills_text: str = "") -> str:
        """
        Generates the system prompt for the Chat/RAG pipeline.
        """
        base = BluecoinsPersona._get_base_system_prompt()
        
        skills_section = ""
        if active_skills_text:
             skills_section = f"\n**Active Skills:**\n{active_skills_text}\n"
        
        instruction = (
            "\n**Instructions:**\n"
            "- Answer the user's question based *only* on the retrieved context below.\n"
            "- If the valid context is empty or irrelevant, politely say you don't have that information.\n"
            "- Prefer concrete numbers and short bullet points over long paragraphs.\n"
            "- Mention specific account names or categories if they appear in the context.\n"
            "- **IMPORTANT**: Do NOT list the sources or transactions at the end. I will append the source list automatically.\n"
        )
        
        return f"{base}{skills_section}{instruction}"

    @staticmethod
    def get_intent_prompt() -> str:
        """
        Generates the system prompt for Intent Classification.
        """
        return (
            "You are an intent classifier for a personal finance bot (Bluecoins Manager).\n"
            "Analyze the user message and return a JSON object with the detected intent and entities.\n\n"
            "**Intents:**\n"
            "- `ADD_TRANSACTION`: User wants to log a new expense or income.\n"
            "- `ADD_ACCOUNT`: User wants to create a new bank/financial account.\n"
            "- `ADD_CATEGORY`: User wants to create a new budget category.\n"
            "- `LIST_ACCOUNTS`: User wants to see their accounts.\n"
            "- `LIST_CATEGORIES`: User wants to see their budget structure.\n"
            "- `LIST_RULEBOOK`: User wants to see AI knowledge or fine-tune examples.\n"
            "- `REVIEW_QUEUE`: User wants to process pending transactions.\n"
            "- `MODIFY_TRANSACTION`: User wants to edit a specific existing transaction.\n"
            "- `GREETING`: User is saying hello, hi, or goodbye.\n"
            "- `CHAT_QUERY`: Default intent for general questions, reports, or advice.\n\n"
            "**Entities to extract:**\n"
            "- `amount` (float)\n"
            "- `description` (string)\n"
            "- `name` (string - for account or category)\n"
            "- `transaction_id` (integer - for modifications)\n\n"
            "**Return JSON ONLY in this format:**\n"
            "{\n"
            "  \"intent\": \"INTENT_NAME\",\n"
            "  \"entities\": {\n"
            "    \"amount\": null,\n"
            "    \"description\": null,\n"
            "    \"name\": null,\n"
            "    \"transaction_id\": null\n"
            "  },\n"
            "  \"confidence\": 0.0-1.0\n"
            "}\n"
        )
