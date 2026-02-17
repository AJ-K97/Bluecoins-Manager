---
phase: 19
plan: 1
wave: 1
---

# Plan 19.1: Remote LLM Configuration

## Objective
Enable the application to connect to a remote Ollama instance (e.g., over Tailscale) by centralizing client configuration and respecting the `OLLAMA_HOST` environment variable.

## Context
- src/local_llm.py
- src/intents.py
- src/ai.py (CategorizerAI)

## Tasks

<task type="auto">
  <name>Create AI Config Module</name>
  <files>src/ai_config.py</files>
  <action>
    Create `src/ai_config.py`:
    - Define `get_ollama_client() -> ollama.AsyncClient`.
    - Read `OLLAMA_HOST` from env (default to 127.0.0.1:11434 if missing).
    - Log client initialization target for debugging.
  </action>
  <verify>test -f src/ai_config.py</verify>
  <done>Module created</done>
</task>

<task type="auto">
  <name>Refactor IntentAI</name>
  <files>src/intents.py</files>
  <action>
    Update `IntentAI.__init__`:
    - Remove direct `ollama.AsyncClient()` call.
    - Use `get_ollama_client()`.
  </action>
  <verify>grep "get_ollama_client" src/intents.py</verify>
  <done>IntentAI uses centralized config</done>
</task>

<task type="auto">
  <name>Refactor LocalLLMPipeline</name>
  <files>src/local_llm.py</files>
  <action>
    Update `LocalLLMPipeline.__init__`:
    - Use `get_ollama_client()`.
  </action>
  <verify>grep "get_ollama_client" src/local_llm.py</verify>
  <done>LocalLLMPipeline uses centralized config</done>
</task>

<task type="auto">
  <name>Refactor CategorizerAI</name>
  <files>src/ai.py</files>
  <action>
    Update `CategorizerAI` (if exists and uses ollama):
    - Use `get_ollama_client()`.
  </action>
  <verify>grep "get_ollama_client" src/ai.py</verify>
  <done>CategorizerAI uses centralized config</done>
</task>

## Success Criteria
- [ ] All AI components use `OLLAMA_HOST` from `.env`.
- [ ] Users can point to remote Tailscale IP.
