"""Extract dealer phone numbers from dealer website HTML."""
from __future__ import annotations

import json
import re
from html import unescape

# US phone patterns (10-digit core; optional +1).
_PHONE_CORE = r"(?:\+?1[-.\s]?)?\(?([2-9]\d{2})\)?[-.\s]?([2-9]\d{2})[-.\s]?(\d{4})"
_PHONE_RE = re.compile(_PHONE_CORE)
_TEL_HREF_RE = re.compile(r"href\s*=\s*['\"]tel:([^'\"]+)['\"]", re.I)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_DATA_PHONE_RE = re.compile(
    r'data-(?:phone|tel|phonenumber)\s*=\s*["\']([^"\']+)["\']',
    re.I,
)
_ITEMPROP_PHONE_RE = re.compile(
    r'itemprop=["\']telephone["\'][^>]*>([^<]+)<',
    re.I,
)
_META_PHONE_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:og:phone_number|telephone)["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)

_INVALID_PLACEHOLDERS = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "not specified",
        "0000000000",
        "1234567890",
        "5555555555",
    }
)


def _digits_only(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def normalize_us_phone(raw: str) -> str | None:
    """Return E.164-style +1XXXXXXXXXX when a valid US number is found."""
    if not raw:
        return None
    text = unescape(raw).strip()
    if text.lower() in _INVALID_PLACEHOLDERS:
        return None

    digits = _digits_only(text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        m = _PHONE_RE.search(text)
        if not m:
            return None
        digits = "".join(m.groups())

    if len(digits) != 10 or digits[0] in "01" or digits[3] in "01":
        return None
    if digits in _INVALID_PLACEHOLDERS:
        return None
    return f"+1{digits}"


def _phones_from_json_ld(html: str) -> list[str]:
    found: list[str] = []
    for block in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                tel = node.get("telephone") or node.get("phone")
                if isinstance(tel, str):
                    found.append(tel)
                elif isinstance(tel, list):
                    found.extend(str(t) for t in tel)
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    return found


def extract_phones_from_html(html: str) -> list[str]:
    """Collect normalized US phone numbers from HTML, best-first order."""
    candidates: list[str] = []

    for m in _TEL_HREF_RE.findall(html):
        candidates.append(m)
    for m in _DATA_PHONE_RE.findall(html):
        candidates.append(m)
    for m in _ITEMPROP_PHONE_RE.findall(html):
        candidates.append(m)
    for m in _META_PHONE_RE.findall(html):
        candidates.append(m)
    candidates.extend(_phones_from_json_ld(html))
    for m in _PHONE_RE.findall(html[:120_000]):
        candidates.append(f"({m[0]}) {m[1]}-{m[2]}")

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in candidates:
        norm = normalize_us_phone(raw)
        if norm and norm not in seen:
            seen.add(norm)
            ordered.append(norm)
    return ordered


def extract_primary_phone(html: str) -> str | None:
    phones = extract_phones_from_html(html)
    return phones[0] if phones else None
