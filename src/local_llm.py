import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ollama
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database import (
    Category,
    LLMFineTuneExample,
    LLMKnowledgeChunk,
    LLMSkill,
    Transaction,
)
from src.persona import BluecoinsPersona


@dataclass
class RetrievalHit:
    score: float
    content: str
    metadata: Dict[str, Any]


def _safe_json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


class LocalLLMPipeline:
    def __init__(self, chat_model: str = "llama3.1:8b", embedding_model: str = "nomic-embed-text"):
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.client = ollama.AsyncClient(host=os.getenv("OLLAMA_HOST"))

    async def _embed_text(self, text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return []

        # Support both newer `embed` and older `embeddings` endpoints.
        try:
            resp = await self.client.embed(model=self.embedding_model, input=text)
            embedding = resp.get("embeddings", [[]])[0]
            if embedding:
                return embedding
        except Exception:
            pass

        resp = await self.client.embeddings(model=self.embedding_model, prompt=text)
        return resp.get("embedding", [])

    async def _chat(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.chat(
            model=self.chat_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.1},
        )
        return response["message"]["content"].strip()

    def _transaction_to_chunk(self, tx: Transaction) -> Tuple[str, Dict[str, Any]]:
        parent = tx.category.parent_name if tx.category else None
        category = tx.category.name if tx.category else None
        meta = {
            "transaction_id": tx.id,
            "date": tx.date.isoformat() if tx.date else None,
            "amount": tx.amount,
            "type": tx.type,
            "account": tx.account.name if tx.account else None,
            "category_parent": parent,
            "category_name": category,
            "is_verified": bool(tx.is_verified),
        }
        content = (
            f"Transaction #{tx.id}\n"
            f"Date: {meta['date']}\n"
            f"Description: {tx.description}\n"
            f"Amount: {tx.amount}\n"
            f"Type: {tx.type}\n"
            f"Account: {meta['account']}\n"
            f"Category: {parent} > {category}\n"
            f"Verified: {meta['is_verified']}"
        )
        return content, meta

    async def add_skill(
        self,
        session,
        name: str,
        instruction: str,
        description: Optional[str] = None,
        priority: int = 100,
    ) -> Tuple[bool, str]:
        name = (name or "").strip()
        instruction = (instruction or "").strip()
        if not name or not instruction:
            return False, "Both name and instruction are required."

        existing = await session.execute(select(LLMSkill).where(LLMSkill.name == name))
        row = existing.scalar_one_or_none()
        if row:
            row.instruction = instruction
            row.description = description
            row.priority = priority
            row.is_active = True
            session.add(row)
            await session.commit()
            return True, f"Updated skill '{name}'."

        session.add(
            LLMSkill(
                name=name,
                instruction=instruction,
                description=description,
                priority=priority,
                is_active=True,
            )
        )
        await session.commit()
        return True, f"Added skill '{name}'."

    async def list_skills(self, session, active_only: bool = False) -> List[LLMSkill]:
        stmt = select(LLMSkill).order_by(LLMSkill.priority.asc(), LLMSkill.name.asc())
        if active_only:
            stmt = stmt.where(LLMSkill.is_active.is_(True))
        rows = await session.execute(stmt)
        return rows.scalars().all()

    async def set_skill_active(self, session, name: str, is_active: bool) -> Tuple[bool, str]:
        row = await session.execute(select(LLMSkill).where(LLMSkill.name == name))
        skill = row.scalar_one_or_none()
        if not skill:
            return False, f"Skill '{name}' not found."
        skill.is_active = bool(is_active)
        session.add(skill)
        await session.commit()
        return True, f"Skill '{name}' {'enabled' if is_active else 'disabled'}."

    async def reindex_transactions(self, session, since: Optional[datetime] = None) -> Dict[str, int]:
        stmt = (
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.account))
            .order_by(Transaction.id.asc())
        )
        if since:
            stmt = stmt.where(Transaction.date >= since)

        result = await session.execute(stmt)
        txs = result.scalars().all()

        created = 0
        updated = 0
        skipped = 0

        for tx in txs:
            content, metadata = self._transaction_to_chunk(tx)
            vector = await self._embed_text(content)
            if not vector:
                skipped += 1
                continue

            existing = await session.execute(
                select(LLMKnowledgeChunk).where(
                    LLMKnowledgeChunk.source_type == "transaction",
                    LLMKnowledgeChunk.source_id == tx.id,
                )
            )
            row = existing.scalar_one_or_none()

            if row:
                row.content = content
                row.metadata_json = json.dumps(metadata)
                row.embedding_model = self.embedding_model
                row.embedding_vector = json.dumps(vector)
                row.updated_at = datetime.utcnow()
                session.add(row)
                updated += 1
            else:
                session.add(
                    LLMKnowledgeChunk(
                        source_type="transaction",
                        source_id=tx.id,
                        content=content,
                        metadata_json=json.dumps(metadata),
                        embedding_model=self.embedding_model,
                        embedding_vector=json.dumps(vector),
                    )
                )
                created += 1

        await session.commit()
        await session.commit()
        return {"created": created, "updated": updated, "skipped": skipped, "total": len(txs)}

    async def extract_search_filters(self, query: str) -> Dict[str, Any]:
        """
        Uses LLM to extract structured filters (date, amount, etc.) from the user query.
        """
        system_prompt = (
            "You are a sophisticated query parser for a financial database.\n"
            "Extract search filters from the user's natural language query.\n"
            "Return JSON ONLY.\n\n"
            "Supported Keys:\n"
            "- start_date (YYYY-MM-DD)\n"
            "- end_date (YYYY-MM-DD)\n"
            "- min_amount (float)\n"
            "- max_amount (float)\n"
            "- account_name (string)\n"
            "- category_name (string)\n\n"
            "Example:\n"
            "User: 'transactions over $500 last month'\n"
            "Output: {\"min_amount\": 500, \"start_date\": \"2024-01-01\", \"end_date\": \"2024-01-31\"}\n\n"
            f"Current Date: {datetime.now().strftime('%Y-%m-%d')}"
        )
        
        try:
            resp = await self._chat(system_prompt, query)
            # Clean response (sometimes LLMs add markdown code blocks)
            cleaned = resp.replace("```json", "").replace("```", "").strip()
            filters = json.loads(cleaned)
            return filters
        except Exception as e:
            # Fallback to empty filters on error
            print(f"Filter extraction failed: {e}")
            return {}

    async def retrieve(self, session, query: str, top_k: int = 8, filters: Dict[str, Any] = None) -> List[RetrievalHit]:
        qvec = await self._embed_text(query)
        if not qvec:
            return []

        # Start with base query
        # We need to join LLMKnowledgeChunk with Transaction to apply filters
        stmt = (
            select(LLMKnowledgeChunk)
            .join(Transaction, LLMKnowledgeChunk.source_id == Transaction.id)
            .where(
                LLMKnowledgeChunk.embedding_model == self.embedding_model,
                LLMKnowledgeChunk.source_type == "transaction"
            )
        )

        # Apply Filters
        if filters:
            if filters.get("start_date"):
                try:
                    stmt = stmt.where(Transaction.date >= datetime.strptime(filters["start_date"], "%Y-%m-%d"))
                except ValueError: pass
            if filters.get("end_date"):
                try:
                    stmt = stmt.where(Transaction.date <= datetime.strptime(filters["end_date"], "%Y-%m-%d"))
                except ValueError: pass
            if filters.get("min_amount") is not None:
                stmt = stmt.where(Transaction.amount >= float(filters["min_amount"]))
            if filters.get("max_amount") is not None:
                stmt = stmt.where(Transaction.amount <= float(filters["max_amount"]))
            if filters.get("account_name"):
                # Case-insensitive partial match? Or join Account table? 
                # Joined transaction has account_id, but we need name. 
                # Let's join Account as well if needed, or rely on metadata/denormalization?
                # Transaction schema has relation 'account'.
                # Let's do a join.
                # Note: Transaction is already joined. We need another join?
                # We can join relation `Transaction.account`
                from src.database import Account
                stmt = stmt.join(Account, Transaction.account_id == Account.id)
                stmt = stmt.where(Account.name.ilike(f"%{filters['account_name']}%"))
            
            if filters.get("category_name"):
                from src.database import Category
                # Transaction already joined? No.
                # Transaction is joined at line 262.
                # We need to join Transaction using its relation?
                # or just join Category on Transaction.category_id
                stmt = stmt.join(Category, Transaction.category_id == Category.id)
                stmt = stmt.where(Category.name.ilike(f"%{filters['category_name']}%"))

        rows = await session.execute(stmt)
        chunks = rows.scalars().all()

        scored: List[RetrievalHit] = []
        for c in chunks:
            vec = _safe_json_loads(c.embedding_vector, [])
            score = _cosine_similarity(qvec, vec)
            # Filter out low-relevance hits (noise)
            if score < 0.25:
                continue
            scored.append(
                RetrievalHit(
                    score=score,
                    content=c.content,
                    metadata=_safe_json_loads(c.metadata_json, {}),
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[: max(1, top_k)]

    async def _build_system_prompt(self, session) -> str:
        rows = await session.execute(
            select(LLMSkill).where(LLMSkill.is_active.is_(True)).order_by(LLMSkill.priority.asc(), LLMSkill.name.asc())
        )
        skills = rows.scalars().all()
        skill_lines = []
        for s in skills:
            skill_lines.append(f"- [{s.name}] {s.instruction}")

        skill_block = "\n".join(skill_lines) if skill_lines else "- No custom skills configured yet."

        return BluecoinsPersona.get_chat_prompt(skill_block)

    async def answer(self, session, query: str, top_k: int = 8) -> Dict[str, Any]:
        # 1. Parse Filters
        filters = await self.extract_search_filters(query)
        
        # 2. Retrieve with filters
        hits = await self.retrieve(session, query, top_k=top_k, filters=filters)
        
        context_block = "\n\n".join(
            [f"[score={h.score:.4f}]\n{h.content}" for h in hits]
        )
        if not context_block:
            context_block = "No indexed transaction context found."

        system_prompt = await self._build_system_prompt(session)
        user_prompt = (
            f"User question: {query}\n\n"
            "Retrieved Context:\n"
            f"{context_block}\n\n"
            "Answer based on context and active skills."
        )

        answer = await self._chat(system_prompt, user_prompt)
        
        # Append structured sources
        source_block = BluecoinsPersona.format_sources(hits)
        final_answer = f"{answer}{source_block}"
        
        return {
            "answer": final_answer,
            "contexts": [
                {
                    "score": h.score,
                    "transaction_id": h.metadata.get("transaction_id"),
                    "content": h.content,
                }
                for h in hits
            ],
        }

    async def refresh_finetune_examples(self, session) -> Dict[str, int]:
        rows = await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.category))
            .where(Transaction.is_verified.is_(True), Transaction.category_id.is_not(None))
        )
        verified = rows.scalars().all()

        existing_rows = await session.execute(select(LLMFineTuneExample))
        existing = {
            e.source_transaction_id: e
            for e in existing_rows.scalars().all()
        }

        created = 0
        updated = 0

        for tx in verified:
            if not tx.category:
                continue

            prompt = (
                "Classify the transaction into the exact category and type.\n"
                f"Description: {tx.description}\n"
                f"Amount: {tx.amount}\n"
                f"Date: {tx.date.isoformat() if tx.date else ''}\n"
            )
            response_obj = {
                "type": tx.type,
                "category_parent": tx.category.parent_name,
                "category_name": tx.category.name,
            }
            response = json.dumps(response_obj, ensure_ascii=True)

            row = existing.get(tx.id)
            if row:
                row.prompt = prompt
                row.response = response
                session.add(row)
                updated += 1
            else:
                session.add(
                    LLMFineTuneExample(
                        source_transaction_id=tx.id,
                        prompt=prompt,
                        response=response,
                    )
                )
                created += 1

        await session.commit()
        return {"created": created, "updated": updated, "total_verified": len(verified)}

    async def export_finetune_jsonl(self, session, output_path: str) -> Dict[str, Any]:
        await self.refresh_finetune_examples(session)

        rows = await session.execute(select(LLMFineTuneExample).order_by(LLMFineTuneExample.id.asc()))
        examples = rows.scalars().all()

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with out.open("w", encoding="utf-8") as f:
            for ex in examples:
                line = {
                    "messages": [
                        {"role": "system", "content": "You classify personal finance transactions."},
                        {"role": "user", "content": ex.prompt},
                        {"role": "assistant", "content": ex.response},
                    ]
                }
                f.write(json.dumps(line, ensure_ascii=True) + "\n")

        return {"output_path": str(out), "examples": len(examples)}
