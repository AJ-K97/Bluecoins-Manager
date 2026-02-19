import asyncio
import json
import math
import threading
import webbrowser
from collections import Counter, defaultdict
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from src.database import AIMemory, AsyncSessionLocal, Category, Transaction


@dataclass
class EdgeAccumulator:
    keyword: str
    category_id: Optional[int]
    count: int = 0
    confidence_sum: float = 0.0
    confidence_count: int = 0
    verified_count: int = 0
    reason_counts: Counter = field(default_factory=Counter)
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


@dataclass
class InitialGuessAccumulator:
    keyword: str
    category_id: int
    miss_count: int = 0
    correction_count: int = 0
    decay_score: float = 0.0
    reason_counts: Counter = field(default_factory=Counter)
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


def _clean_keyword(raw_keyword: Optional[str]) -> str:
    keyword = (raw_keyword or "").strip()
    return " ".join(keyword.split())


def _clean_reason(raw_reason: Optional[str]) -> str:
    text = " ".join((raw_reason or "").strip().split())
    if not text:
        return ""
    max_len = 180
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _coerce_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_float(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Optional[str], default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _node_size(total_weight: float, base: float) -> float:
    return round(base + min(34.0, math.sqrt(max(0.1, total_weight)) * 4.0), 2)


def _as_utc_datetime(raw_value) -> Optional[datetime]:
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        if raw_value.tzinfo is None:
            return raw_value.replace(tzinfo=timezone.utc)
        return raw_value.astimezone(timezone.utc)
    if isinstance(raw_value, date):
        return datetime.combine(raw_value, time.min, tzinfo=timezone.utc)
    return None


def _iso_date(raw_value) -> Optional[str]:
    parsed = _as_utc_datetime(raw_value)
    if parsed is None:
        return None
    return parsed.date().isoformat()


def _update_bounds(bounds: dict, node_id: str, seen_at: Optional[datetime]) -> None:
    if seen_at is None:
        return
    slot = bounds.setdefault(node_id, {"first": None, "last": None})
    first = slot["first"]
    last = slot["last"]
    if first is None or seen_at < first:
        slot["first"] = seen_at
    if last is None or seen_at > last:
        slot["last"] = seen_at


def _resolve_category_id(
    user_selected_category_id: Optional[int],
    tx_category_id: Optional[int],
    ai_suggested_category_id: Optional[int],
) -> Optional[int]:
    if user_selected_category_id is not None:
        return user_selected_category_id
    if tx_category_id is not None:
        return tx_category_id
    return ai_suggested_category_id


def _category_label_from_map(category_id: Optional[int], category_map: Dict[int, dict]) -> str:
    if category_id is None:
        return "Uncategorized > Uncategorized [unknown]"
    category_meta = category_map.get(
        category_id,
        {"parent_name": "Unknown", "name": "Unknown", "type": "unknown"},
    )
    return f"{category_meta['parent_name']} > {category_meta['name']} [{category_meta['type']}]"


async def _fetch_category_map(session, category_ids) -> Dict[int, dict]:
    category_map = {}
    if not category_ids:
        return category_map
    cat_res = await session.execute(
        select(Category.id, Category.parent_name, Category.name, Category.type).where(
            Category.id.in_(category_ids)
        )
    )
    for category_id, parent_name, name, category_type in cat_res.all():
        category_map[category_id] = {
            "parent_name": parent_name or "Uncategorized",
            "name": name or "Uncategorized",
            "type": category_type or "unknown",
        }
    return category_map


async def build_keyword_category_graph(
    session,
    *,
    min_weight: float = 0.0,
    limit: int = 250,
    verified_only: bool = False,
    include_uncategorized: bool = False,
    include_transactions: bool = False,
    tx_per_keyword: int = 12,
    tx_node_limit: int = 700,
):
    stmt = (
        select(
            AIMemory.pattern_key,
            AIMemory.user_selected_category_id,
            AIMemory.ai_suggested_category_id,
            AIMemory.ai_reasoning,
            AIMemory.transaction_id,
            Transaction.category_id,
            Transaction.confidence_score,
            Transaction.is_verified,
            Transaction.decision_reason,
            Transaction.description,
            Transaction.amount,
            Transaction.date,
            Transaction.type,
        )
        .join(Transaction, Transaction.id == AIMemory.transaction_id)
    )
    if verified_only:
        stmt = stmt.where(Transaction.is_verified.is_(True))

    res = await session.execute(stmt)
    rows = res.all()

    accumulators: Dict[Tuple[str, Optional[int]], EdgeAccumulator] = {}
    keyword_transactions: Dict[str, list] = defaultdict(list)
    keyword_events: Dict[str, list] = defaultdict(list)
    seen_keyword_tx = set()
    category_ids = set()

    for (
        pattern_key,
        user_selected_category_id,
        ai_suggested_category_id,
        ai_reasoning,
        transaction_id,
        tx_category_id,
        confidence_score,
        is_verified,
        decision_reason,
        tx_description,
        tx_amount,
        tx_date,
        tx_type,
    ) in rows:
        keyword = _clean_keyword(pattern_key)
        if not keyword:
            continue

        category_id = _resolve_category_id(
            user_selected_category_id, tx_category_id, ai_suggested_category_id
        )
        if category_id is None and not include_uncategorized:
            continue

        key = (keyword, category_id)
        edge = accumulators.get(key)
        if edge is None:
            edge = EdgeAccumulator(keyword=keyword, category_id=category_id)
            accumulators[key] = edge

        edge.count += 1
        if confidence_score is not None:
            edge.confidence_sum += float(confidence_score)
            edge.confidence_count += 1
        if is_verified:
            edge.verified_count += 1

        reason_text = _clean_reason(ai_reasoning or decision_reason)
        if reason_text:
            edge.reason_counts[reason_text] += 1

        tx_dt = _as_utc_datetime(tx_date)
        if tx_dt is not None:
            if edge.first_seen_at is None or tx_dt < edge.first_seen_at:
                edge.first_seen_at = tx_dt
            if edge.last_seen_at is None or tx_dt > edge.last_seen_at:
                edge.last_seen_at = tx_dt

        if category_id is not None:
            category_ids.add(category_id)
        if ai_suggested_category_id is not None:
            category_ids.add(ai_suggested_category_id)

        keyword_events[keyword].append(
            {
                "resolved_category_id": category_id,
                "suggested_category_id": ai_suggested_category_id,
                "reason": reason_text,
                "tx_dt": tx_dt,
            }
        )

        if transaction_id is not None:
            tx_key = (keyword, int(transaction_id))
            if tx_key not in seen_keyword_tx:
                seen_keyword_tx.add(tx_key)
                keyword_transactions[keyword].append(
                    {
                        "transaction_id": int(transaction_id),
                        "description": (tx_description or "").strip(),
                        "amount": float(tx_amount) if tx_amount is not None else None,
                        "date": _iso_date(tx_date),
                        "type": (tx_type or "").strip() or "unknown",
                        "confidence": float(confidence_score) if confidence_score is not None else 0.0,
                    }
                )

    category_map = await _fetch_category_map(session, category_ids)

    edges = []
    for edge in accumulators.values():
        avg_confidence = (
            edge.confidence_sum / edge.confidence_count if edge.confidence_count > 0 else 0.5
        )
        verified_ratio = edge.verified_count / edge.count if edge.count else 0.0
        weight = edge.count * (0.6 + 0.4 * avg_confidence) * (1.0 + 0.3 * verified_ratio)
        if weight < min_weight:
            continue

        reasons = [
            {"text": text, "count": count}
            for text, count in edge.reason_counts.most_common(3)
        ]
        reason = reasons[0]["text"] if reasons else "No explicit reason captured."

        source_id = f"keyword::{edge.keyword}"
        if edge.category_id is None:
            target_id = "category::uncategorized"
            category_label = "Uncategorized > Uncategorized [unknown]"
            category_type = "unknown"
        else:
            category_meta = category_map.get(
                edge.category_id,
                {"parent_name": "Unknown", "name": "Unknown", "type": "unknown"},
            )
            category_label = _category_label_from_map(edge.category_id, category_map)
            category_type = category_meta["type"]
            target_id = f"category::{edge.category_id}"

        edges.append(
            {
                "id": f"{source_id}->{target_id}",
                "source": source_id,
                "target": target_id,
                "edge_type": "keyword_category",
                "keyword": edge.keyword,
                "category_id": edge.category_id,
                "category_label": category_label,
                "category_type": category_type,
                "reason": reason,
                "reasons": reasons,
                "count": edge.count,
                "avg_confidence": round(avg_confidence, 4),
                "verified_ratio": round(verified_ratio, 4),
                "weight": round(weight, 4),
                "first_seen_date": _iso_date(edge.first_seen_at),
                "last_seen_date": _iso_date(edge.last_seen_at),
            }
        )

    total_edges_before_limit = len(edges)
    edges.sort(key=lambda item: item["weight"], reverse=True)
    edges = edges[:limit]

    selected_keywords = {edge["keyword"] for edge in edges}
    initial_guess_edges = []
    decay_lambda = 0.38
    initial_guess_accumulators: Dict[Tuple[str, int], InitialGuessAccumulator] = {}

    for keyword, events in keyword_events.items():
        if keyword not in selected_keywords:
            continue

        ordered_events = sorted(
            events,
            key=lambda item: (
                item["tx_dt"] is None,
                item["tx_dt"] or datetime.max.replace(tzinfo=timezone.utc),
            ),
        )
        total_correct = sum(
            1
            for item in ordered_events
            if item["resolved_category_id"] is not None
            and item["suggested_category_id"] is not None
            and item["resolved_category_id"] == item["suggested_category_id"]
        )
        running_correct = 0

        for item in ordered_events:
            resolved_category_id = item["resolved_category_id"]
            suggested_category_id = item["suggested_category_id"]
            tx_dt = item["tx_dt"]

            if resolved_category_id is None or suggested_category_id is None:
                continue

            if resolved_category_id == suggested_category_id:
                running_correct += 1
                continue

            future_correct = max(0, total_correct - running_correct)
            residual = math.exp(-decay_lambda * future_correct)
            acc_key = (keyword, int(suggested_category_id))
            acc = initial_guess_accumulators.get(acc_key)
            if acc is None:
                acc = InitialGuessAccumulator(keyword=keyword, category_id=int(suggested_category_id))
                initial_guess_accumulators[acc_key] = acc

            acc.miss_count += 1
            acc.correction_count = max(acc.correction_count, total_correct)
            acc.decay_score += residual
            reason_text = item["reason"] or "LLM initially selected this category."
            acc.reason_counts[reason_text] += 1

            if tx_dt is not None:
                if acc.first_seen_at is None or tx_dt < acc.first_seen_at:
                    acc.first_seen_at = tx_dt
                if acc.last_seen_at is None or tx_dt > acc.last_seen_at:
                    acc.last_seen_at = tx_dt

    for miss in initial_guess_accumulators.values():
        category_meta = category_map.get(
            miss.category_id,
            {"parent_name": "Unknown", "name": "Unknown", "type": "unknown"},
        )
        source_id = f"keyword::{miss.keyword}"
        target_id = f"category::{miss.category_id}"
        category_label = (
            f"{category_meta['parent_name']} > {category_meta['name']} [{category_meta['type']}]"
        )
        reasons = [
            {"text": text, "count": count}
            for text, count in miss.reason_counts.most_common(3)
        ]
        reason = reasons[0]["text"] if reasons else "LLM initially selected this category."
        decay_strength = (
            miss.decay_score / miss.miss_count if miss.miss_count > 0 else 0.0
        )
        weight = max(0.1, min(1.6, 0.2 + miss.decay_score * 0.68))
        initial_guess_edges.append(
            {
                "id": f"{source_id}->{target_id}::llm-initial",
                "source": source_id,
                "target": target_id,
                "edge_type": "llm_initial_category",
                "keyword": miss.keyword,
                "category_id": miss.category_id,
                "category_label": category_label,
                "category_type": category_meta["type"],
                "reason": reason,
                "reasons": reasons,
                "count": miss.miss_count,
                "miss_count": miss.miss_count,
                "correction_count": miss.correction_count,
                "decay_strength": round(decay_strength, 4),
                "weight": round(weight, 4),
                "first_seen_date": _iso_date(miss.first_seen_at),
                "last_seen_date": _iso_date(miss.last_seen_at),
            }
        )

    if initial_guess_edges:
        edges.extend(initial_guess_edges)

    tx_node_lookup = {}
    if include_transactions and edges:
        keyword_set = {edge["keyword"] for edge in edges if edge.get("edge_type") != "transaction_keyword"}
        tx_edges = []
        tx_nodes = {}
        tx_added = 0
        for keyword in keyword_set:
            transactions = keyword_transactions.get(keyword) or []
            transactions.sort(key=lambda row: row.get("date") or "", reverse=True)
            for tx in transactions[: max(1, tx_per_keyword)]:
                if tx_added >= tx_node_limit:
                    break
                tx_id = tx["transaction_id"]
                tx_node_id = f"transaction::{tx_id}"
                keyword_node_id = f"keyword::{keyword}"
                if tx_node_id not in tx_nodes:
                    label = tx["description"] or f"TX {tx_id}"
                    if len(label) > 56:
                        label = label[:53] + "..."
                    tx_nodes[tx_node_id] = {
                        "id": tx_node_id,
                        "label": label,
                        "kind": "transaction",
                        "transaction_id": tx_id,
                        "description": tx["description"],
                        "amount": tx["amount"],
                        "date": tx["date"],
                        "tx_type": tx["type"],
                        "size": 3.2,
                    }
                    tx_node_lookup[tx_node_id] = tx_nodes[tx_node_id]
                    tx_added += 1

                tx_confidence = tx.get("confidence") or 0.0
                tx_weight = round(0.18 + min(0.5, tx_confidence * 0.45), 4)
                tx_edges.append(
                    {
                        "id": f"{tx_node_id}->{keyword_node_id}",
                        "source": tx_node_id,
                        "target": keyword_node_id,
                        "edge_type": "transaction_keyword",
                        "keyword": keyword,
                        "reason": "Transaction matched resolved keyword.",
                        "reasons": [{"text": "Transaction matched resolved keyword.", "count": 1}],
                        "count": 1,
                        "avg_confidence": round(tx_confidence, 4),
                        "verified_ratio": 0.0,
                        "weight": tx_weight,
                        "transaction_id": tx_id,
                        "transaction_label": tx_nodes[tx_node_id]["label"],
                        "transaction_date": tx.get("date"),
                    }
                )

            if tx_added >= tx_node_limit:
                break

        if tx_edges:
            edges.extend(tx_edges)

    node_weight = defaultdict(float)
    node_timeline_bounds = {}
    for edge in edges:
        if edge.get("edge_type") == "keyword_category":
            multiplier = 1.0
        elif edge.get("edge_type") == "llm_initial_category":
            multiplier = 0.5
        else:
            multiplier = 0.2
        node_weight[edge["source"]] += edge["weight"] * multiplier
        node_weight[edge["target"]] += edge["weight"] * multiplier
        edge_first = _as_utc_datetime(edge.get("first_seen_date") or edge.get("transaction_date"))
        edge_last = _as_utc_datetime(edge.get("last_seen_date") or edge.get("transaction_date"))
        _update_bounds(node_timeline_bounds, edge["source"], edge_first)
        _update_bounds(node_timeline_bounds, edge["target"], edge_last or edge_first)

    keyword_nodes = {}
    category_nodes = {}
    transaction_nodes = {}
    for edge in edges:
        source_id = edge["source"]
        target_id = edge["target"]
        keyword_label = edge["keyword"]
        if source_id.startswith("keyword::") and source_id not in keyword_nodes:
            keyword_bounds = node_timeline_bounds.get(source_id) or {}
            keyword_nodes[source_id] = {
                "id": source_id,
                "label": keyword_label,
                "kind": "keyword",
                "size": _node_size(node_weight[source_id], base=10.0),
                "first_seen_date": _iso_date(keyword_bounds.get("first")),
                "last_seen_date": _iso_date(keyword_bounds.get("last")),
            }
        if source_id.startswith("transaction::"):
            tx = dict(
                tx_node_lookup.get(source_id)
                or {
                    "id": source_id,
                    "label": edge.get("transaction_label") or source_id,
                    "kind": "transaction",
                    "transaction_id": edge.get("transaction_id"),
                    "size": 3.2,
                }
            )
            tx_date = tx.get("date") or edge.get("transaction_date")
            if tx_date:
                tx["first_seen_date"] = tx_date
                tx["last_seen_date"] = tx_date
            transaction_nodes[source_id] = tx

        if target_id.startswith("category::") and target_id not in category_nodes:
            category_bounds = node_timeline_bounds.get(target_id) or {}
            category_nodes[target_id] = {
                "id": target_id,
                "label": edge["category_label"],
                "kind": "category",
                "category_id": edge["category_id"],
                "category_type": edge["category_type"],
                "size": _node_size(node_weight[target_id], base=14.0),
                "first_seen_date": _iso_date(category_bounds.get("first")),
                "last_seen_date": _iso_date(category_bounds.get("last")),
            }
        if target_id.startswith("transaction::"):
            tx = dict(
                tx_node_lookup.get(target_id)
                or {
                    "id": target_id,
                    "label": edge.get("transaction_label") or target_id,
                    "kind": "transaction",
                    "transaction_id": edge.get("transaction_id"),
                    "size": 3.2,
                }
            )
            tx_date = tx.get("date") or edge.get("transaction_date")
            if tx_date:
                tx["first_seen_date"] = tx_date
                tx["last_seen_date"] = tx_date
            transaction_nodes[target_id] = tx

    nodes = list(keyword_nodes.values()) + list(category_nodes.values()) + list(
        transaction_nodes.values()
    )

    timeline_points = set()
    for node in nodes:
        for key in ("first_seen_date", "last_seen_date", "date"):
            value = node.get(key)
            if value:
                timeline_points.add(value)
    for edge in edges:
        for key in ("first_seen_date", "last_seen_date", "transaction_date"):
            value = edge.get(key)
            if value:
                timeline_points.add(value)

    sorted_timeline_points = sorted(timeline_points)
    timeline = {
        "points": sorted_timeline_points,
        "start": sorted_timeline_points[0] if sorted_timeline_points else None,
        "end": sorted_timeline_points[-1] if sorted_timeline_points else None,
        "count": len(sorted_timeline_points),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "min_weight": min_weight,
            "limit": limit,
            "verified_only": verified_only,
            "include_uncategorized": include_uncategorized,
            "include_transactions": include_transactions,
            "tx_per_keyword": tx_per_keyword,
            "tx_node_limit": tx_node_limit,
        },
        "stats": {
            "rows_scanned": len(rows),
            "unique_pairs": len(accumulators),
            "initial_miss_edges": len(initial_guess_edges),
            "total_edges_after_filter": total_edges_before_limit,
            "total_edges_after_limit": len(edges),
            "total_nodes": len(nodes),
            "timeline_points": timeline["count"],
        },
        "timeline": timeline,
        "nodes": nodes,
        "edges": edges,
    }


async def build_quality_report(
    session,
    *,
    confusion_limit: int = 10,
    replay_months: int = 18,
):
    stmt = (
        select(
            AIMemory.pattern_key,
            AIMemory.user_selected_category_id,
            AIMemory.ai_suggested_category_id,
            AIMemory.transaction_id,
            AIMemory.created_at,
            Transaction.category_id,
            Transaction.confidence_score,
            Transaction.date,
        )
        .join(Transaction, Transaction.id == AIMemory.transaction_id)
    )
    res = await session.execute(stmt)
    rows = res.all()

    category_ids = set()
    scored = []
    for (
        _pattern_key,
        user_selected_category_id,
        ai_suggested_category_id,
        transaction_id,
        memory_created_at,
        tx_category_id,
        confidence_score,
        tx_date,
    ) in rows:
        resolved_category_id = _resolve_category_id(
            user_selected_category_id, tx_category_id, ai_suggested_category_id
        )
        predicted_category_id = ai_suggested_category_id
        if resolved_category_id is None or predicted_category_id is None:
            continue

        category_ids.add(int(resolved_category_id))
        category_ids.add(int(predicted_category_id))
        observed_at = _as_utc_datetime(tx_date) or _as_utc_datetime(memory_created_at)
        scored.append(
            {
                "transaction_id": int(transaction_id) if transaction_id is not None else None,
                "actual": int(resolved_category_id),
                "predicted": int(predicted_category_id),
                "confidence": float(confidence_score) if confidence_score is not None else None,
                "observed_at": observed_at,
            }
        )

    category_map = await _fetch_category_map(session, category_ids)

    total_scored = len(scored)
    correct_count = sum(1 for row in scored if row["actual"] == row["predicted"])
    accuracy = (correct_count / total_scored) if total_scored > 0 else 0.0

    category_stats = defaultdict(
        lambda: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "support": 0,
            "predicted_count": 0,
        }
    )
    for row in scored:
        actual = row["actual"]
        predicted = row["predicted"]
        category_stats[actual]["support"] += 1
        category_stats[predicted]["predicted_count"] += 1
        if actual == predicted:
            category_stats[actual]["tp"] += 1
        else:
            category_stats[actual]["fn"] += 1
            category_stats[predicted]["fp"] += 1

    per_category = []
    macro_f1_total = 0.0
    macro_f1_count = 0
    for category_id, stats in category_stats.items():
        tp = stats["tp"]
        fp = stats["fp"]
        fn = stats["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        macro_f1_total += f1
        macro_f1_count += 1
        per_category.append(
            {
                "category_id": category_id,
                "category_label": _category_label_from_map(category_id, category_map),
                "support": stats["support"],
                "predicted_count": stats["predicted_count"],
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        )

    per_category.sort(key=lambda item: (item["support"], item["f1"]), reverse=True)
    macro_f1 = (macro_f1_total / macro_f1_count) if macro_f1_count > 0 else 0.0

    confusion_limit = max(4, min(20, int(confusion_limit or 10)))
    top_actual_ids = [item["category_id"] for item in per_category[:confusion_limit]]
    confusion_counts = defaultdict(int)
    for row in scored:
        actual = row["actual"]
        predicted = row["predicted"]
        if actual in top_actual_ids and predicted in top_actual_ids:
            confusion_counts[(actual, predicted)] += 1

    confusion_rows = []
    for actual in top_actual_ids:
        row_counts = [confusion_counts.get((actual, predicted), 0) for predicted in top_actual_ids]
        confusion_rows.append(
            {
                "actual_category_id": actual,
                "actual_label": _category_label_from_map(actual, category_map),
                "support": sum(row_counts),
                "counts": row_counts,
            }
        )

    calibration_bins = []
    raw_bins = [
        {"sum_confidence": 0.0, "correct": 0, "count": 0, "start": idx / 10, "end": (idx + 1) / 10}
        for idx in range(10)
    ]
    for row in scored:
        confidence = row["confidence"]
        if confidence is None:
            continue
        confidence = max(0.0, min(1.0, confidence))
        idx = min(9, int(confidence * 10))
        raw_bins[idx]["count"] += 1
        raw_bins[idx]["sum_confidence"] += confidence
        if row["actual"] == row["predicted"]:
            raw_bins[idx]["correct"] += 1

    for bucket in raw_bins:
        count = bucket["count"]
        avg_confidence = (bucket["sum_confidence"] / count) if count > 0 else None
        bucket_accuracy = (bucket["correct"] / count) if count > 0 else None
        calibration_bins.append(
            {
                "range_start": round(bucket["start"], 2),
                "range_end": round(bucket["end"], 2),
                "count": count,
                "avg_confidence": round(avg_confidence, 4) if avg_confidence is not None else None,
                "accuracy": round(bucket_accuracy, 4) if bucket_accuracy is not None else None,
            }
        )

    monthly = defaultdict(lambda: {"count": 0, "correct": 0})
    for row in scored:
        observed_at = row["observed_at"]
        if observed_at is None:
            continue
        month_key = observed_at.strftime("%Y-%m")
        monthly[month_key]["count"] += 1
        if row["actual"] == row["predicted"]:
            monthly[month_key]["correct"] += 1

    sorted_months = sorted(monthly.keys())
    if replay_months > 0:
        sorted_months = sorted_months[-max(3, min(48, int(replay_months))):]
    replay_points = []
    cumulative_count = 0
    cumulative_correct = 0
    for month_key in sorted_months:
        row = monthly[month_key]
        count = row["count"]
        correct = row["correct"]
        cumulative_count += count
        cumulative_correct += correct
        replay_points.append(
            {
                "period": month_key,
                "count": count,
                "correct": correct,
                "accuracy": round(correct / count, 4) if count > 0 else 0.0,
                "cumulative_accuracy": (
                    round(cumulative_correct / cumulative_count, 4) if cumulative_count > 0 else 0.0
                ),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_scored": total_scored,
            "correct": correct_count,
            "accuracy": round(accuracy, 4),
            "macro_f1": round(macro_f1, 4),
            "categories_covered": len(per_category),
        },
        "per_category": per_category,
        "confusion": {
            "labels": [
                {"category_id": category_id, "label": _category_label_from_map(category_id, category_map)}
                for category_id in top_actual_ids
            ],
            "rows": confusion_rows,
        },
        "calibration": calibration_bins,
        "replay": replay_points,
    }


async def build_replay_report(
    session,
    *,
    months: int = 18,
):
    report = await build_quality_report(session, replay_months=months)
    replay_points = report.get("replay", [])
    best_period = None
    worst_period = None
    if replay_points:
        best_period = max(replay_points, key=lambda item: item["accuracy"])
        worst_period = min(replay_points, key=lambda item: item["accuracy"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": report.get("summary", {}),
        "months": replay_points,
        "best_period": best_period,
        "worst_period": worst_period,
    }


async def _graph_payload_from_query(query):
    min_weight = _coerce_float(query.get("min_weight", [None])[0], default=0.0)
    limit = _coerce_int(query.get("limit", [None])[0], default=250, minimum=25, maximum=1000)
    verified_only = _coerce_bool(query.get("verified_only", [None])[0], default=False)
    include_uncategorized = _coerce_bool(
        query.get("include_uncategorized", [None])[0], default=False
    )
    include_transactions = _coerce_bool(query.get("include_transactions", [None])[0], default=False)
    tx_per_keyword = _coerce_int(
        query.get("tx_per_keyword", [None])[0],
        default=12,
        minimum=2,
        maximum=40,
    )
    tx_node_limit = _coerce_int(
        query.get("tx_node_limit", [None])[0],
        default=700,
        minimum=100,
        maximum=3000,
    )

    async with AsyncSessionLocal() as session:
        return await build_keyword_category_graph(
            session,
            min_weight=min_weight,
            limit=limit,
            verified_only=verified_only,
            include_uncategorized=include_uncategorized,
            include_transactions=include_transactions,
            tx_per_keyword=tx_per_keyword,
            tx_node_limit=tx_node_limit,
        )


async def _quality_payload_from_query(query):
    confusion_limit = _coerce_int(
        query.get("confusion_limit", [None])[0],
        default=10,
        minimum=4,
        maximum=20,
    )
    replay_months = _coerce_int(
        query.get("replay_months", [None])[0],
        default=18,
        minimum=3,
        maximum=48,
    )
    async with AsyncSessionLocal() as session:
        return await build_quality_report(
            session,
            confusion_limit=confusion_limit,
            replay_months=replay_months,
        )


async def _replay_payload_from_query(query):
    months = _coerce_int(
        query.get("months", [None])[0],
        default=18,
        minimum=3,
        maximum=48,
    )
    async with AsyncSessionLocal() as session:
        return await build_replay_report(session, months=months)


class AsyncLoopRunner:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        def _run_loop():
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self._ready.set()
            loop.run_forever()

            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

        self._thread = threading.Thread(target=_run_loop, name="graph-web-async-loop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._loop is None:
            raise RuntimeError("Failed to start async loop runner.")

    def run(self, coroutine, timeout: float = 180.0):
        if self._loop is None:
            raise RuntimeError("Async loop runner is not started.")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError("Async API task timed out.") from exc

    def stop(self):
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
        self._loop = None
        self._thread = None
        self._ready.clear()


class GraphRequestHandler(SimpleHTTPRequestHandler):
    async_runner = None

    def _run_async(self, coroutine):
        runner = type(self).async_runner
        if runner is None:
            raise RuntimeError("Async runner not initialized.")
        return runner.run(coroutine)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/graph":
            self._serve_graph_payload(parse_qs(parsed.query))
            return
        if parsed.path == "/api/quality":
            self._serve_quality_payload(parse_qs(parsed.query))
            return
        if parsed.path == "/api/replay":
            self._serve_replay_payload(parse_qs(parsed.query))
            return

        if parsed.path in {"", "/"}:
            self.path = "/graph.html"
        super().do_GET()

    def _serve_graph_payload(self, query):
        try:
            payload = self._run_async(_graph_payload_from_query(query))
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            data = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_quality_payload(self, query):
        try:
            payload = self._run_async(_quality_payload_from_query(query))
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            data = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_replay_payload(self, query):
        try:
            payload = self._run_async(_replay_payload_from_query(query))
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            data = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_graph_web_server(host: str, port: int, open_browser: bool = False):
    static_dir = Path(__file__).resolve().parent.parent / "webapp"
    graph_page = static_dir / "graph.html"
    if not graph_page.exists():
        raise FileNotFoundError(f"Expected webapp page at {graph_page}")

    async_runner = AsyncLoopRunner()
    async_runner.start()
    GraphRequestHandler.async_runner = async_runner

    handler = partial(GraphRequestHandler, directory=str(static_dir))
    server = ThreadingHTTPServer((host, port), handler)

    base_url = f"http://{host}:{port}"
    print(f"Graph webapp running at {base_url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(base_url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping graph webapp.")
    finally:
        server.server_close()
        GraphRequestHandler.async_runner = None
        async_runner.stop()


async def serve_graph_web_server(host: str, port: int, open_browser: bool = False):
    await asyncio.to_thread(run_graph_web_server, host, port, open_browser)
