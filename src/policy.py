from dataclasses import dataclass
from typing import Iterable, List, Union, Optional


AUTO_APPROVE_MIN = 0.97
REVIEW_MIN = 0.70
POLICY_VERSION = "conservative_v1"


@dataclass
class DecisionResult:
    state: str
    priority: int
    bucket: str
    reason: str
    can_auto_verify: bool


def _normalize_flags(conflict_flags: Optional[Iterable[str]]) -> List[str]:
    if not conflict_flags:
        return []
    return sorted({str(x).strip().lower() for x in conflict_flags if str(x).strip()})


def evaluate_decision_policy(confidence: float, conflict_flags: Optional[Iterable[str]] = None) -> DecisionResult:
    conf = float(confidence or 0.0)
    flags = _normalize_flags(conflict_flags)

    if flags:
        return DecisionResult(
            state="force_review",
            priority=10,
            bucket="rule_conflict",
            reason=f"Conflict flags present: {', '.join(flags)}",
            can_auto_verify=False,
        )

    if conf >= AUTO_APPROVE_MIN:
        return DecisionResult(
            state="auto_approved",
            priority=90,
            bucket="high_confidence",
            reason=f"Confidence {conf:.2f} >= {AUTO_APPROVE_MIN:.2f} and no conflicts.",
            can_auto_verify=True,
        )

    if conf < REVIEW_MIN:
        return DecisionResult(
            state="force_review",
            priority=20,
            bucket="conf_low",
            reason=f"Confidence {conf:.2f} below review minimum {REVIEW_MIN:.2f}.",
            can_auto_verify=False,
        )

    return DecisionResult(
        state="needs_review",
        priority=50,
        bucket="conf_mid",
        reason=(
            f"Confidence {conf:.2f} in review band "
            f"[{REVIEW_MIN:.2f}, {AUTO_APPROVE_MIN:.2f})."
        ),
        can_auto_verify=False,
    )
