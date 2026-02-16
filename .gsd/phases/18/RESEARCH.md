# Phase 18 Research: Remote LLM Integration

## Current Implementation
- **LocalLLMPipeline**: Correctly uses `os.getenv("OLLAMA_HOST")` when initializing `ollama.AsyncClient`.
- **IntentAI**: Initializes `ollama.AsyncClient()` with defaults, ignoring `OLLAMA_HOST` env var if not strictly set in environment where python runs (but explicit passing is safer).
- **CategorizerAI**: (Likely similar, need to check).

## Strategy
1. **Centralize Client Creation**: Create a helper `get_ollama_client()` in a shared module (e.g., `src/ai_config.py` or existing `src/utils.py`) that strictly reads `OLLAMA_HOST`.
2. **Update Consumers**: Refactor `LocalLLMPipeline`, `IntentAI`, and `CategorizerAI` to use this helper.
3. **Environment Config**: Document `OLLAMA_HOST` in `.env.example`.
4. **Timeout Handling**: Remote connections might be slower. Configure request timeouts if supported by the client library (or ensure defaults are sufficient).

## Verification
- Set `OLLAMA_HOST` to a mock or the user's remote IP.
- Run a simple script calling `IntentAI.classify` and verify it connects to the target host.
