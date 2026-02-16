---
phase: 17
plan: 1
wave: 1
---

# Plan 17.1: Standardized Response Formatting

## Objective
Implement consistent response formatting with programmatic source attribution to improve trust and readability.

## Context
- src/persona.py
- src/local_llm.py

## Tasks

<task type="auto">
  <name>Enhance Persona Helpers</name>
  <files>src/persona.py</files>
  <action>
    Add methods to `BluecoinsPersona`:
    - `format_currency(amount: float) -> str` (e.g., "$1,234.56")
    - `format_sources(hits: List[RetrievalHit]) -> str`
        - Returns a formatted string: "\n\n**Sources:**\n1. {Date} - {Description} ({Amount})\n..."
  </action>
  <verify>grep "def format_sources" src/persona.py</verify>
  <done>Helpers implemented</done>
</task>

<task type="auto">
  <name>Update Prompt Instructions</name>
  <files>src/persona.py</files>
  <action>
    Update `get_chat_prompt`:
    - Instruct LLM to **NOT** list sources manually (since we append them).
    - Instruct LLM to use specific headers (e.g., "Summary", "Breakdown").
  </action>
  <verify>grep "NOT list sources" src/persona.py</verify>
  <done>Prompt updated to delegate source listing to code</done>
</task>

<task type="auto">
  <name>Integrate Formatting in Pipeline</name>
  <files>src/local_llm.py</files>
  <action>
    Modify `LocalLLMPipeline.answer`:
    - Generate LLM response.
    - Generate Source block using `BluecoinsPersona.format_sources(hits)`.
    - Combine `final_answer = llm_response + source_block`.
    - Return this combined string as the answer.
  </action>
  <verify>grep "BluecoinsPersona.format_sources" src/local_llm.py</verify>
  <done>Pipeline appends sources programmatically</done>
</task>

## Success Criteria
- [ ] Responses have clear "Answer" and "Sources" sections.
- [ ] Sources are accurate (programmatic) vs hallucinated.
- [ ] Currency numbers are consistently formatted.
