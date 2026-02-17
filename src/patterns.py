import re
from dataclasses import dataclass
from typing import Optional


DATE_TOKEN_RE = re.compile(r"\b\d{2}[A-Z]{3}\d{2}\b", re.IGNORECASE)
DATE_SLASH_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b")
SPACE_RE = re.compile(r"\s+")
REF_TOKEN_RE = re.compile(r"\b[A-Z0-9]{6,}\b")
LEADING_NUMBER_RE = re.compile(r"^\d+$")
LEGAL_PREFIX_RE = re.compile(r"^\s*(THE\s+TRUSTEE\s+FOR|PTY\s+LTD|TRUST)\s+", re.IGNORECASE)

PAYEE_PATTERNS = [
    re.compile(r"\bPAYMENT\s+FROM\s+(?P<payee>.+)$", re.IGNORECASE),
    re.compile(r"\bPAYMENT\s+TO\s+(?P<payee>.+)$", re.IGNORECASE),
    re.compile(r"\bTRANSFER\s+FROM\s+(?P<payee>.+)$", re.IGNORECASE),
    re.compile(r"\bTRANSFER\s+TO\s+(?P<payee>.+)$", re.IGNORECASE),
]

NOISE_TOKENS = {
    "VISA", "DEBIT", "CREDIT", "CARD", "PURCHASE", "ATM", "EFTPOS", "AUD", "INTERNET", "BANKING",
    "EFFECTIVE", "DATE", "ATMA", "POS", "PAYWAVE", "MASTERCARD",
}

TAIL_STOP_TOKENS = {
    "AU", "AUS", "WA", "NSW", "VIC", "QLD", "SA", "NT", "TAS",
}

GENERIC_TOKENS = {
    "VISA", "PAYMENT", "TRANSFER", "DEBIT", "CREDIT", "CARD", "PURCHASE", "ATM", "EFTPOS",
}


@dataclass
class PatternKeyResult:
    keyword: str
    confidence: float
    source: str
    tokens_used: list


def _clean_text(description: str) -> str:
    text = SPACE_RE.sub(" ", str(description or "").replace("\xa0", " ")).strip()
    text = LEGAL_PREFIX_RE.sub("", text).strip()
    return text


def _strip_common_noise(text: str) -> str:
    cleaned = DATE_TOKEN_RE.sub(" ", text)
    cleaned = DATE_SLASH_RE.sub(" ", cleaned)
    cleaned = TIME_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("/", " / ")
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _remove_reference_tokens(tokens):
    out = []
    for t in tokens:
        token = t.strip(" ,.-")
        if not token:
            continue
        if LEADING_NUMBER_RE.match(token):
            continue
        if REF_TOKEN_RE.match(token) and token.upper() not in {"WOOLWORTHS", "OFFICEWORKS"}:
            continue
        out.append(token)
    return out


def _truncate_location_tail(tokens):
    # Conservative tail trimming for obvious location tails.
    out = list(tokens)
    while out and out[-1].upper() in TAIL_STOP_TOKENS:
        out.pop()
    return out


def _clean_payee_phrase(payee: str) -> str:
    text = _strip_common_noise(_clean_text(payee))
    # Remove common trailing banking boilerplate from payee phrases.
    text = re.sub(r"\b(JOINT\s+BANK\s+TRANSFER?|INTERNET\s+BANKING)\b.*$", "", text, flags=re.IGNORECASE).strip()
    text = SPACE_RE.sub(" ", text).strip(" -|,")
    return text


def _rule_based_extract(description: str) -> PatternKeyResult:
    if not description:
        return PatternKeyResult(keyword="UNKNOWN", confidence=0.0, source="fallback", tokens_used=[])

    raw = _clean_text(description)
    if not raw:
        return PatternKeyResult(keyword="UNKNOWN", confidence=0.0, source="fallback", tokens_used=[])

    # 1) Explicit payee transfer/payment patterns.
    for pat in PAYEE_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        payee = _clean_payee_phrase(m.group("payee"))
        if payee:
            tokens = [t for t in payee.split() if t]
            return PatternKeyResult(
                keyword=payee.upper()[:80],
                confidence=0.90 if len(tokens) >= 2 else 0.78,
                source="rule",
                tokens_used=tokens[:8],
            )

    # 2) Date-token preamble (legacy strong behavior).
    date_match = DATE_TOKEN_RE.search(raw)
    if date_match:
        pre_date = raw[:date_match.start()].strip(" -|,")
        pre_date = LEGAL_PREFIX_RE.sub("", pre_date).strip()
        pre_date = SPACE_RE.sub(" ", pre_date)
        if pre_date:
            tokens = [t for t in pre_date.split() if t]
            return PatternKeyResult(
                keyword=pre_date.upper()[:80],
                confidence=0.82 if len(tokens) >= 2 else 0.72,
                source="rule",
                tokens_used=tokens[:8],
            )

    # 3) Merchant before slash (common merchant/location format).
    slash_match = re.search(r"\b([A-Z][A-Z0-9&'.\-]{2,})\s*/", raw, re.IGNORECASE)
    if slash_match:
        merchant = slash_match.group(1).strip(" -|,")
        if merchant:
            return PatternKeyResult(
                keyword=merchant.upper()[:80],
                confidence=0.80,
                source="rule",
                tokens_used=[merchant.upper()],
            )

    # 4) General token cleanup and phrase extraction.
    cleaned = _strip_common_noise(raw)
    tokens = _remove_reference_tokens(cleaned.split())
    tokens = [t for t in tokens if t.upper() not in NOISE_TOKENS]
    tokens = _truncate_location_tail(tokens)

    if tokens:
        # Prefer first 1-3 meaningful tokens to reduce location tails.
        candidate = " ".join(tokens[:3]).strip()
        if candidate:
            generic = tokens[0].upper() in GENERIC_TOKENS
            conf = 0.60 if not generic else 0.35
            return PatternKeyResult(
                keyword=candidate.upper()[:80],
                confidence=conf,
                source="rule",
                tokens_used=[t.upper() for t in tokens[:6]],
            )

    # 5) Final fallback.
    words = raw.split()
    word = words[0].upper() if words else "UNKNOWN"
    conf = 0.15 if word in GENERIC_TOKENS else 0.30
    return PatternKeyResult(keyword=word, confidence=conf, source="fallback", tokens_used=[word] if word else [])


def extract_pattern_key_result(description: str, resolver: Optional[object] = None) -> PatternKeyResult:
    """
    Structured keyword extraction.
    If a resolver is provided and exposes `resolve_sync(description)`, it will be used.
    """
    if resolver and hasattr(resolver, "resolve_sync"):
        try:
            resolved = resolver.resolve_sync(description)
            if isinstance(resolved, PatternKeyResult):
                return resolved
        except Exception:
            pass
    return _rule_based_extract(description)


def extract_pattern_key(description: str) -> str:
    """
    Backward-compatible shim returning keyword only.
    """
    return extract_pattern_key_result(description).keyword
