import re


DATE_TOKEN_RE = re.compile(r"\b\d{2}[A-Z]{3}\d{2}\b", re.IGNORECASE)
LEGAL_PREFIX_RE = re.compile(r"^\s*(THE\s+TRUSTEE\s+FOR|PTY\s+LTD|TRUST)\s+", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")


def extract_pattern_key(description):
    """
    Extract a stable merchant-like key.
    Rule:
    1. If DDMMMYY token exists, use text before first date token.
    2. If no date token, fallback to first word (legacy behavior).
    """
    if not description:
        return "UNKNOWN"

    text = SPACE_RE.sub(" ", str(description).replace("\xa0", " ")).strip()
    if not text:
        return "UNKNOWN"

    match = DATE_TOKEN_RE.search(text)
    if match:
        pre_date = text[:match.start()].strip(" -|,")
        pre_date = LEGAL_PREFIX_RE.sub("", pre_date).strip()
        pre_date = SPACE_RE.sub(" ", pre_date)
        if pre_date:
            return pre_date.upper()[:80]

    words = text.split()
    return words[0].upper() if words else "UNKNOWN"
