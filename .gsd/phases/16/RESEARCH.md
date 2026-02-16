# Phase 16 Research: Enhanced Context Retrieval

## Current State Analysis
- **Model**: `LocalLLMPipeline` uses `nomic-embed-text` with cosine similarity.
- **Chunking**: Transactions are converted to text "chunks" in `_transaction_to_chunk`.
- **Retrieval**: Simple semantic search (`retrieve` method).
- **Gaps**:
    - **No Time Awareness**: Semantic search searches descriptions/amounts but ignores "last month" or "2024" in the query unless explicitly mentioned in the text chunk.
    - **No Structured Filtering**: Cannot ask "transactions over $500" reliably if it relies solely on vector similarity.
    - **Limited Context**: Only pulls 8 chunks (`top_k=8`), which is insufficient for "summarize my spending" queries.

## Improvement Strategy

### 1. Hybrid Search (SQL + Vector)
- **Concept**: Use LLM to extract filters (date range, amount, category) *before* retrieval.
- **Implementation**:
    - Update `IntentAI` or create `QueryParser` to extract: `min_amount`, `max_amount`, `start_date`, `end_date`, `account`.
    - Modify `retrieve` to accept these filters and apply them via SQLAlchemy *before* or *during* selection.

### 2. Time-Aware Context
- **Concept**: Inject "Current Date" into the system prompt so the LLM knows what "this month" means.
- **Status**: Already done in standard prompts usually, but need to verify `persona.py` includes it.

### 3. "Smart Summary" Retrieval
- **Problem**: "How much did I spend on food?" requires aggregating *all* food transactions, not just top 8.
- **Solution**:
    - Detect "Aggregation" intent.
    - If aggregation, use SQL query to fetch data instead of RAG chunks.
    - Pass the SQL result (summary) to the LLM context.

## Proposed Plan (Phase 16)
Focus on **Structure-Aware Retrieval**.
1.  **Query Parsing**: Extract filters from natural language.
2.  **Filtered Retrieval**: Apply SQLAlchemy filters to the `LLMKnowledgeChunk` selection (join with Transaction table? Or rely on metadata).
    - *Note*: `LLMKnowledgeChunk` stores `metadata_json`. Querying JSON in SQLite/Postgres is possible but might be slow or complex across DB types.
    - *Better approach*: Join `LLMKnowledgeChunk` with `Transaction` on `source_id`.

### Execution Steps
1.  **Refactor `retrieve`**: Add `filters` argument.
2.  **Implement Filter Logic**: Join with `Transaction` table to apply date/amount filters.
3.  **Update `answer`**: Parse query for filters -> Pass to `retrieve`.
