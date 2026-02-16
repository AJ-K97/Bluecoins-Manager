# Phase 17 Research: Response Formatting

## Current Issues
- **Inconsistent Output**: LLM responses vary in structure. Sometimes lists, sometimes paragraphs.
- **Hidden Sources**: The user doesn't know *which* transactions contributed to an answer.
- **Raw Numbers**: Currency formatting might be inconsistent ($500 vs 500).

## Design Specification

### 1. Standardized Output Structure
All RAG responses should follow this Markdown structure:
```markdown
**Direct Answer**: One sentence summary.

**Details**:
- Bullet points with specific data.
- **$120.50** at **Shell** (Jan 12)

**Sources**:
1. Transaction #101 (Shell, $50.00)
2. Transaction #105 (Shell, $70.50)
```

### 2. Implementation Logic
- **Prompt Engineering**: Update `BluecoinsPersona.get_chat_prompt` to explicitly request this structure.
- **Post-Processing**:
    - Move "Sources" generation out of the LLM (hallucination risk) and into Python.
    - `LocalLLMPipeline` should append the "Sources" block programmatically based on the retrieved `search_results`.

### 3. Formatting Helpers
- Add `BluecoinsPersona.format_currency(amount)`
- Add `BluecoinsPersona.format_source_list(hits)`
