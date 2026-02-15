# Local LLM Pipeline (Private, Incremental, Skill-Driven)

This project now includes a local-first LLM pipeline designed for your exact goal:

- keep all data local,
- adapt behavior to your finance workflow,
- improve over time as more verified transactions are added.

The implementation is in `src/local_llm.py` and is exposed via `main.py llm ...` commands.

## 1) Architecture Overview

The pipeline has 5 stages:

1. **Ingestion**
- Transactions are imported into PostgreSQL using existing flow (`convert` / interactive review).
- Verified transactions are especially important because they become high-quality learning examples.

2. **Knowledge Indexing (RAG memory)**
- Each transaction is transformed into a text chunk.
- Chunk embedding is generated with a local embedding model (`nomic-embed-text` by default via Ollama).
- Embeddings are stored in `llm_knowledge_chunks`.
- Re-running indexing updates existing chunks and adds new ones.

3. **Skill Layer (your custom behavior)**
- You define explicit, persistent skills (instructions) in `llm_skills`.
- Skills are injected into the system prompt in priority order.
- This is the strongest way to enforce specific behavior without retraining each time.

4. **Question Answering**
- User query is embedded.
- Most relevant indexed transactions are retrieved by cosine similarity.
- Query + retrieved context + active skills are sent to local chat model.
- Model answers using your data and instructions.

5. **Incremental Fine-Tuning Dataset Loop**
- Verified transactions are converted into supervised examples and stored in `llm_finetune_examples`.
- Export to JSONL for periodic LoRA fine-tuning jobs.
- This gives longer-term model adaptation while RAG handles immediate updates.

## 2) Database Tables Added

Defined in `src/database.py`:

- `llm_knowledge_chunks`
  - Stores transaction chunks + embedding vectors.
- `llm_skills`
  - Stores custom instruction rules, priority, active flag.
- `llm_finetune_examples`
  - Stores prompt/response pairs derived from verified transactions.

`init_db()` will create these tables automatically when you run `main.py`.

## 3) Setup Prerequisites

1. Start DB:
```bash
docker-compose up -d
```

2. Start Ollama:
```bash
ollama serve
```

3. Pull models (example defaults):
```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

4. Install dependencies (if not already):
```bash
pip install -r requirements.txt
```

## 4) CLI Commands

All commands are under `main.py llm`.

### A. Reindex transactions into embeddings

```bash
python3 main.py llm reindex
```

What it does:
- reads transactions from DB,
- builds text chunks,
- computes embeddings,
- upserts into `llm_knowledge_chunks`.

Rebuild category intent memory (used by categorization prompts):
```bash
python3 main.py llm rebuild-category-understanding
```

### B. Ask questions against your indexed data

```bash
python3 main.py llm ask --query "What did I spend most on last month?"
```

Optional debug context:
```bash
python3 main.py llm ask --query "Show recent Uber spends" --show-context
```

### C. Add custom skills

```bash
python3 main.py llm skill-add \
  --name "strict-category-policy" \
  --instruction "Never invent categories; if uncertain, say uncertain and request review." \
  --description "Conservative categorization behavior" \
  --priority 10
```

List skills:
```bash
python3 main.py llm skill-list
```

Enable/disable skill:
```bash
python3 main.py llm skill-enable --name "strict-category-policy"
python3 main.py llm skill-disable --name "strict-category-policy"
```

### D. Export fine-tune dataset

```bash
python3 main.py llm export-finetune --output data/finetune/transactions_train.jsonl
```

This export is generated from verified transactions.

## 5) Recommended Daily/Weekly Workflow

Daily:
1. Import new statements.
2. Review and verify categories.
3. Run `python3 main.py llm reindex`.
4. Use `llm ask` for analysis and decision support.
5. Process queue (`python3 main.py queue review`) for `needs_review` and `force_review` items.

Weekly or monthly:
1. Run `export-finetune`.
2. Run a LoRA training job on the JSONL.
3. Evaluate before replacing production local model.

## 6) Fine-Tuning Strategy (Practical)

Use **RAG for immediate learning** and **LoRA for periodic consolidation**.

Why:
- Retraining a full model on every transaction is expensive and unstable.
- RAG updates instantly when new transactions are indexed.
- LoRA improves base behavior over time from verified examples.

### Example LoRA process (high-level)

1. Export examples:
```bash
python3 main.py llm export-finetune --output data/finetune/transactions_train.jsonl
```

2. Train adapter using your preferred local trainer (Unsloth / Axolotl / LlamaFactory).

3. Keep versioned artifacts, evaluate, then deploy as your active model.

4. Continue RAG indexing even after LoRA; they complement each other.

## 7) Prompt/Skill Design Guidance

Good skill instructions are:
- explicit,
- testable,
- conflict-free,
- short.

Good examples:
- "If transfer confidence < 0.85, return 'needs_review' instead of guessing."
- "For recurring subscriptions, include monthly trend and 3-month average."
- "When merchant text is noisy, ignore card suffixes and terminal IDs."

Avoid:
- vague instructions like "be smart".
- conflicting rules with same priority.

## 8) Operational Notes

- Entire inference and indexing pipeline can run locally with Ollama.
- If you switch embedding model, reindex to keep vector space consistent.
- If no context is indexed, answers will be limited; run `llm reindex` first.
- For quality, prioritize transaction verification because this drives better fine-tune examples.
- Conservative queue policy is active:
  - auto-approve only when confidence >= 0.97 and no conflicts.
  - 0.70-0.9699 goes to `needs_review`.
  - below 0.70 or any conflict goes to `force_review`.

## 9) Key Files

- `src/local_llm.py`: pipeline service (index/retrieve/ask/skills/export).
- `src/database.py`: new tables for chunks, skills, fine-tune examples.
- `main.py`: CLI integration under `llm` command.
- `docs/LOCAL_LLM_PIPELINE.md`: this runbook.

## 10) Quick Start

```bash
# 1) import data using existing workflow
python3 main.py

# 2) index for retrieval
python3 main.py llm reindex

# 3) add your behavior rule
python3 main.py llm skill-add --name "review-first" --instruction "If uncertain, recommend review." --priority 10

# 4) ask questions
python3 main.py llm ask --query "Summarize eating-out spend in the last 30 days"

# 5) export examples for periodic LoRA
python3 main.py llm export-finetune
```
