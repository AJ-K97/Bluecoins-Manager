import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import case, func, select

from src.database import Account, Category, Transaction


@dataclass
class AskDBPlan:
    kind: str  # total|by_category|transactions|net
    tx_type: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    account_id: Optional[int]
    account_name: Optional[str]
    category_term: Optional[str]
    limit: int


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _next_month_start(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


def _parse_time_window(query: str, today: date):
    q = query.lower()

    if "today" in q:
        return today, today

    if "ytd" in q or "year to date" in q:
        return date(today.year, 1, 1), today

    if "this month" in q:
        return _month_start(today), today

    if "last month" in q:
        this_month_start = _month_start(today)
        last_month_end = this_month_start - timedelta(days=1)
        return _month_start(last_month_end), last_month_end

    m = re.search(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", q)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        if "day" in unit:
            delta = timedelta(days=value)
        elif "week" in unit:
            delta = timedelta(weeks=value)
        else:
            # Approximation is acceptable for report windows.
            delta = timedelta(days=30 * value)
        return today - delta, today

    m = re.search(r"in\s+(\d{4})-(\d{2})", q)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        if 1 <= month <= 12:
            start = date(year, month, 1)
            end = _next_month_start(start) - timedelta(days=1)
            return start, end

    return None, None


def _parse_tx_type(query: str) -> Optional[str]:
    q = query.lower()
    income_tokens = ["income", "earned", "salary", "paycheck"]
    expense_tokens = ["spend", "spent", "expense", "expenses", "cost"]

    wants_income = any(token in q for token in income_tokens)
    wants_expense = any(token in q for token in expense_tokens)

    if wants_income and not wants_expense:
        return "income"
    if wants_expense and not wants_income:
        return "expense"
    return None


def _parse_kind(query: str) -> str:
    q = query.lower()
    if ("show" in q or "list" in q) and "transaction" in q:
        return "transactions"
    if "top" in q and "categor" in q:
        return "by_category"
    if "net" in q or "cashflow" in q:
        return "net"
    return "total"


async def _match_account(session, query: str):
    account_rows = await session.execute(select(Account.id, Account.name))
    accounts = account_rows.all()
    q = query.lower()
    best = None
    for acc_id, acc_name in accounts:
        name = (acc_name or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered in q:
            if best is None or len(lowered) > len(best[1]):
                best = (acc_id, name)
    return best


def _parse_category_term(query: str) -> Optional[str]:
    q = query.lower().strip()
    m = re.search(r"on\s+([a-z0-9 &/_-]{3,})(?:\s+(?:last|this|in|from|during)\b|$)", q)
    if not m:
        return None
    term = re.sub(r"\s+", " ", m.group(1)).strip()
    banned = {"transactions", "transaction", "income", "expense", "expenses", "month", "week", "day"}
    if term in banned:
        return None
    return term[:60]


async def plan_ask_db_query(session, query: str, limit: int = 10) -> AskDBPlan:
    now = datetime.utcnow().date()
    start_date, end_date = _parse_time_window(query, now)
    tx_type = _parse_tx_type(query)
    kind = _parse_kind(query)
    account_match = await _match_account(session, query)
    category_term = _parse_category_term(query)

    return AskDBPlan(
        kind=kind,
        tx_type=tx_type,
        start_date=start_date,
        end_date=end_date,
        account_id=account_match[0] if account_match else None,
        account_name=account_match[1] if account_match else None,
        category_term=category_term,
        limit=max(1, min(100, int(limit))),
    )


def _apply_common_filters(stmt, plan: AskDBPlan):
    if plan.tx_type:
        stmt = stmt.where(Transaction.type == plan.tx_type)
    if plan.start_date:
        stmt = stmt.where(Transaction.date >= datetime.combine(plan.start_date, datetime.min.time()))
    if plan.end_date:
        stmt = stmt.where(Transaction.date < datetime.combine(plan.end_date + timedelta(days=1), datetime.min.time()))
    if plan.account_id:
        stmt = stmt.where(Transaction.account_id == plan.account_id)
    return stmt


async def run_ask_db_query(session, plan: AskDBPlan):
    if plan.kind == "transactions":
        stmt = select(
            Transaction.id,
            Transaction.date,
            Transaction.description,
            Transaction.amount,
            Transaction.type,
            Account.name,
            Category.parent_name,
            Category.name,
        ).join(Account, Account.id == Transaction.account_id).outerjoin(Category, Category.id == Transaction.category_id)
        stmt = _apply_common_filters(stmt, plan)
        if plan.category_term:
            like = f"%{plan.category_term}%"
            stmt = stmt.where((Category.name.ilike(like)) | (Category.parent_name.ilike(like)))
        stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(plan.limit)
        rows = (await session.execute(stmt)).all()
        return {"kind": "transactions", "rows": rows}

    if plan.kind == "by_category":
        abs_sum = func.sum(func.abs(Transaction.amount)).label("total")
        stmt = (
            select(
                Category.parent_name,
                Category.name,
                Transaction.type,
                func.count(Transaction.id).label("count"),
                abs_sum,
            )
            .outerjoin(Category, Category.id == Transaction.category_id)
        )
        stmt = _apply_common_filters(stmt, plan)
        if plan.category_term:
            like = f"%{plan.category_term}%"
            stmt = stmt.where((Category.name.ilike(like)) | (Category.parent_name.ilike(like)))
        stmt = (
            stmt.group_by(Category.parent_name, Category.name, Transaction.type)
            .order_by(abs_sum.desc().nullslast())
            .limit(plan.limit)
        )
        rows = (await session.execute(stmt)).all()
        return {"kind": "by_category", "rows": rows}

    if plan.kind == "net":
        income_sum = func.sum(case((Transaction.type == "income", Transaction.amount), else_=0.0))
        expense_sum = func.sum(
            case((Transaction.type == "expense", func.abs(Transaction.amount)), else_=0.0)
        )
        stmt = select(income_sum.label("income_total"), expense_sum.label("expense_total"))
        stmt = _apply_common_filters(stmt, plan)
        income_total, expense_total = (await session.execute(stmt)).one()
        income_total = float(income_total or 0.0)
        expense_total = float(expense_total or 0.0)
        return {
            "kind": "net",
            "income_total": income_total,
            "expense_total": expense_total,
            "net": income_total - expense_total,
        }

    # Default: total
    stmt = select(func.count(Transaction.id), func.sum(func.abs(Transaction.amount)))
    stmt = _apply_common_filters(stmt, plan)
    if plan.category_term:
        stmt = stmt.outerjoin(Category, Category.id == Transaction.category_id)
        like = f"%{plan.category_term}%"
        stmt = stmt.where((Category.name.ilike(like)) | (Category.parent_name.ilike(like)))
    count, total = (await session.execute(stmt)).one()
    return {
        "kind": "total",
        "count": int(count or 0),
        "total": float(total or 0.0),
    }


def plan_summary(plan: AskDBPlan) -> str:
    parts = [f"kind={plan.kind}"]
    if plan.tx_type:
        parts.append(f"type={plan.tx_type}")
    if plan.account_name:
        parts.append(f"account={plan.account_name}")
    if plan.start_date or plan.end_date:
        parts.append(f"range={plan.start_date or '-'}..{plan.end_date or '-'}")
    if plan.category_term:
        parts.append(f"category~{plan.category_term}")
    return " | ".join(parts)
