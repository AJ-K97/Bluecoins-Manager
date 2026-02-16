---
phase: 15
plan: 1
wave: 1
---

# Plan 15.1: Implement Persona Module

## Objective
Establish a centralized "Persona" module to manage system prompts and style guidelines, enabling a consistent voice across LLM interactions.

## Context
- .gsd/SPEC.md
- .gsd/phases/15/RESEARCH.md
- src/local_llm.py
- src/intents.py

## Tasks

<task type="auto">
  <name>Create Persona Module</name>
  <files>src/persona.py</files>
  <action>
    Create `src/persona.py` with:
    - `BluecoinsPersona` class.
    - Methods to get `system_prompt` for Chat and Intent classification.
    - Constants for Emojis (SUCCESS, ERROR, MONEY, etc.).
    - Define the core "Steward" persona prompt.
  </action>
  <verify>test -f src/persona.py</verify>
  <done>File exists and contains BluecoinsPersona class</done>
</task>

<task type="auto">
  <name>Refactor LocalLLMPipeline</name>
  <files>src/local_llm.py</files>
  <action>
    Modify `src/local_llm.py`:
    - Import `BluecoinsPersona`.
    - In `_build_system_prompt`, replace hardcoded text with `BluecoinsPersona.get_chat_prompt(skills)`.
    - Ensure "Active Skills" are still injected into the prompt returned by the Persona module.
  </action>
  <verify>grep "BluecoinsPersona" src/local_llm.py</verify>
  <done>LocalLLMPipeline uses Persona module for prompts</done>
</task>

<task type="auto">
  <name>Refactor IntentAI</name>
  <files>src/intents.py</files>
  <action>
    Modify `src/intents.py`:
    - Import `BluecoinsPersona`.
    - In `classify`, use `BluecoinsPersona.get_intent_prompt()` or similar.
    - Keep the JSON structure instructions rigid (persona shouldn't affect JSON output format, but can affect understanding).
  </action>
  <verify>grep "BluecoinsPersona" src/intents.py</verify>
  <done>IntentAI uses Persona module for prompts</done>
</task>

## Success Criteria
- [ ] `src/persona.py` exists as the single source of truth for prompts.
- [ ] `LocalLLMPipeline` generates answers using the new Persona prompt.
- [ ] `IntentAI` functionality remains intact (regression test via usage).
