# Phase 15 Research: Persona & Style Definition

## Current State Analysis

### 1. Intent Classification (`src/intents.py`)
- **Mechanism**: `IntentAI` class uses `ollama` with a hardcoded system prompt.
- **Persona**: None. Pure functional instruction ("You are an intent classifier...").
- **Output**: JSON.

### 2. Chat/RAG Generation (`src/local_llm.py`)
- **Mechanism**: `LocalLLMPipeline.answer` calls `_build_system_prompt`.
- **System Prompt**: Hardcoded. "You are a local financial assistant... Prefer concrete numbers and short bullet points."
- **Context**: Injects "Skills" from the database.
- **Tone**: Functional, dry.

### 3. Bot Interactions (`src/bot.py`)
- **Mechanism**: Direct string replies (e.g., `await update.message.reply_text("✅ Transaction Saved!")`).
- **Style**: Uses emojis (✅, 💰, 🏦) and MarkdownV2/HTML.
- **Consistency**: Fairly consistent, but hardcoded and scattered.

## Design Proposal: "The Bluecoins Steward"

### Persona Profile
- **Name**: Bluecoins Steward (or just "Blue").
- **Role**: Intelligent, proactive financial aide.
- **Tone**: Professional but approachable. Concise. Data-driven. Uses emojis for visual scanning but not excessive.
- **Directives**:
    - **Accuracy First**: Never hallucinate numbers.
    - **Context Aware**: Reference the user's accounts/categories by name.
    - **Transparent**: Admit when data is missing.

### Implementation Strategy

1.  **Centralized Prompts (`src/persona.py`)**
    - Create a new module to hold all system prompts and style constants.
    - Decouple prompt text from logic classes (`IntentAI`, `LocalLLMPipeline`).

2.  **Unified System Prompt Template**
    - Define a master system prompt that defines the persona.
    - Inject this into `LocalLLMPipeline`.

3.  **Style Constants**
    - Define standard emojis for success, error, warning, info.
    - Define standard date formats (YYYY-MM-DD vs "Feb 12").

### Proposed System Prompt (Draft)
```text
You are Bluecoins Steward, an expert personal finance assistant.
Your goal is to help the user understand their financial health using strict data grounding.

Guidelines:
1. Tone: Professional, concise, helpful.
2. Formatting: Use Markdown. Bold key figures (**$50.00**). Use lists for multiple items.
3. Accuracy: Only use provided context. If context is missing, ask for it.
4. Personality: You are a "Steward" — protective of the user's wealth.
```
