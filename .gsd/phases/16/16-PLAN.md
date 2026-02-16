---
phase: 16
plan: 1
wave: 1
---

# Plan 16.1: Hybrid Retrieval Implementation

## Objective
Enhance RAG by implementing Hybrid Search: combining vector similarity with structured SQL filtering (Date, Amount, Account) to improve accuracy for specific queries.

## Context
- src/local_llm.py
- src/persona.py

## Tasks

<task type="auto">
  <name>Update Retrieval Signature</name>
  <files>src/local_llm.py</files>
  <action>
    Modify `LocalLLMPipeline.retrieve`:
    - Accept `filters: Dict` argument (e.g., `{'start_date': ..., 'min_amount': ...}`).
    - In the SQLAlchemy query, join `LLMKnowledgeChunk` with `Transaction`.
    - Apply filters to the `Transaction` columns.
  </action>
  <verify>grep "def retrieve" src/local_llm.py | grep "filters"</verify>
  <done>Signature updated and SQL joins implemented</done>
</task>

<task type="auto">
  <name>Implement Query Parsing</name>
  <files>src/local_llm.py</files>
  <action>
    Add `_parse_query_filters(query: str) -> Dict` to `LocalLLMPipeline`.
    - For now, use a simple heuristic or a lightweight LLM call to extract dates/amounts.
    - *MVP*: Use regex for "over $X" or simple keywords.
    - *Better*: Use `IntentAI` logic (but keep it inside `local_llm` or imports). 
    - *Decision*: Keep it simple. Regex for "after YYYY-MM-DD" or just rely on vector search for now?
    - *Refined Action*: Actually, let's use the LLM "tools" approach or just a specific prompt to extract constraints.
    - Add a method `extract_search_filters(user_query)` that asks the LLM to return JSON filters.
  </action>
  <verify>grep "def extract_search_filters" src/local_llm.py</verify>
  <done>Filter extraction logic added</done>
</task>

<task type="auto">
  <name>Connect Parsing to Answer</name>
  <files>src/local_llm.py</files>
  <action>
    Update `answer` method:
    1. Call `extract_search_filters(query)`.
    2. Pass result to `retrieve(..., filters=filters)`.
  </action>
  <verify>grep "extract_search_filters" src/local_llm.py</verify>
  <done>Answer method orchestrates filtering</done>
</task>

## Success Criteria
- [ ] `retrieve` accepts and applies SQL filters.
- [ ] `answer` automatically narrows down search space based on query constraints (e.g., "transactions last year" filters by date).
