import asyncio
import json
import math
import webbrowser
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


async def build_keyword_category_graph(
    session,
    *,
    min_weight: float = 0.0,
    limit: int = 250,
    verified_only: bool = False,
    include_uncategorized: bool = False,
):
    stmt = (
        select(
            AIMemory.pattern_key,
            AIMemory.user_selected_category_id,
            AIMemory.ai_suggested_category_id,
            AIMemory.ai_reasoning,
            Transaction.category_id,
            Transaction.confidence_score,
            Transaction.is_verified,
            Transaction.decision_reason,
        )
        .join(Transaction, Transaction.id == AIMemory.transaction_id)
    )
    if verified_only:
        stmt = stmt.where(Transaction.is_verified.is_(True))

    res = await session.execute(stmt)
    rows = res.all()

    accumulators: Dict[Tuple[str, Optional[int]], EdgeAccumulator] = {}
    category_ids = set()

    for (
        pattern_key,
        user_selected_category_id,
        ai_suggested_category_id,
        ai_reasoning,
        tx_category_id,
        confidence_score,
        is_verified,
        decision_reason,
    ) in rows:
        keyword = _clean_keyword(pattern_key)
        if not keyword:
            continue

        category_id = (
            user_selected_category_id
            if user_selected_category_id is not None
            else tx_category_id
            if tx_category_id is not None
            else ai_suggested_category_id
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

        if category_id is not None:
            category_ids.add(category_id)

    category_map = {}
    if category_ids:
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
            category_label = (
                f"{category_meta['parent_name']} > {category_meta['name']} "
                f"[{category_meta['type']}]"
            )
            category_type = category_meta["type"]
            target_id = f"category::{edge.category_id}"

        edges.append(
            {
                "id": f"{source_id}->{target_id}",
                "source": source_id,
                "target": target_id,
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
            }
        )

    total_edges_before_limit = len(edges)
    edges.sort(key=lambda item: item["weight"], reverse=True)
    edges = edges[:limit]

    node_weight = defaultdict(float)
    for edge in edges:
        node_weight[edge["source"]] += edge["weight"]
        node_weight[edge["target"]] += edge["weight"]

    keyword_nodes = {}
    category_nodes = {}
    for edge in edges:
        source_id = edge["source"]
        target_id = edge["target"]
        keyword_label = edge["keyword"]
        if source_id not in keyword_nodes:
            keyword_nodes[source_id] = {
                "id": source_id,
                "label": keyword_label,
                "kind": "keyword",
                "size": _node_size(node_weight[source_id], base=10.0),
            }

        if target_id not in category_nodes:
            category_nodes[target_id] = {
                "id": target_id,
                "label": edge["category_label"],
                "kind": "category",
                "category_id": edge["category_id"],
                "category_type": edge["category_type"],
                "size": _node_size(node_weight[target_id], base=14.0),
            }

    nodes = list(keyword_nodes.values()) + list(category_nodes.values())

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "min_weight": min_weight,
            "limit": limit,
            "verified_only": verified_only,
            "include_uncategorized": include_uncategorized,
        },
        "stats": {
            "rows_scanned": len(rows),
            "unique_pairs": len(accumulators),
            "total_edges_after_filter": total_edges_before_limit,
            "total_edges_after_limit": len(edges),
            "total_nodes": len(nodes),
        },
        "nodes": nodes,
        "edges": edges,
    }


async def _graph_payload_from_query(query):
    min_weight = _coerce_float(query.get("min_weight", [None])[0], default=0.0)
    limit = _coerce_int(query.get("limit", [None])[0], default=250, minimum=25, maximum=1000)
    verified_only = _coerce_bool(query.get("verified_only", [None])[0], default=False)
    include_uncategorized = _coerce_bool(
        query.get("include_uncategorized", [None])[0], default=False
    )

    async with AsyncSessionLocal() as session:
        return await build_keyword_category_graph(
            session,
            min_weight=min_weight,
            limit=limit,
            verified_only=verified_only,
            include_uncategorized=include_uncategorized,
        )


class GraphRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/graph":
            self._serve_graph_payload(parse_qs(parsed.query))
            return

        if parsed.path in {"", "/"}:
            self.path = "/graph.html"
        super().do_GET()

    def _serve_graph_payload(self, query):
        try:
            payload = asyncio.run(_graph_payload_from_query(query))
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


async def serve_graph_web_server(host: str, port: int, open_browser: bool = False):
    await asyncio.to_thread(run_graph_web_server, host, port, open_browser)
