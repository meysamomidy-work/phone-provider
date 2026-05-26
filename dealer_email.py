"""Extract dealer email addresses from dealer website HTML."""
from __future__ import annotations

import json
import re
from html import unescape

_MAILTO_RE = re.compile(r"href\s*=\s*['\"]mailto:([^'\"?]+)", re.I)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_DATA_EMAIL_RE = re.compile(
    r'data-(?:email|e-mail|mail)\s*=\s*["\']([^"\']+)["\']',
    re.I,
)
_ITEMPROP_EMAIL_RE = re.compile(
    r'itemprop=["\']email["\'][^>]*>([^<]+)<',
    re.I,
)
_META_EMAIL_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:og:email|email)["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_EMAIL_RE = re.compile(
    r"\b([a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,})\b"
)

_INVALID_LOCAL_PARTS = frozenset(
    {
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "mailer-daemon",
        "postmaster",
        "webmaster",
        "example",
        "test",
        "admin",
    }
)

_BLOCKED_DOMAINS = frozenset(
    {
        "example.com",
        "example.org",
        "sentry.io",
        "wixpress.com",
        "facebook.com",
        "google.com",
        "googleapis.com",
        "cloudflare.com",
        "schema.org",
        "w3.org",
        "localhost",
        "email.com",
        "domain.com",
        "yoursite.com",
    }
)

_BLOCKED_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".css",
    ".js",
)


def _normalize_email(raw: str) -> str | None:
    if not raw:
        return None
    text = unescape(raw).strip().lower()
    if not text or "@" not in text:
        return None
    if any(text.endswith(s) for s in _BLOCKED_SUFFIXES):
        return None

    local, _, domain = text.rpartition("@")
    if not local or not domain or "." not in domain:
        return None
    if domain in _BLOCKED_DOMAINS:
        return None
    if any(domain.endswith(f".{blocked}") for blocked in _BLOCKED_DOMAINS):
        return None

    local_base = local.split("+", 1)[0]
    if local_base in _INVALID_LOCAL_PARTS:
        return None
    if len(local) > 64 or len(domain) > 255:
        return None
    return f"{local}@{domain}"


def _emails_from_json_ld(html: str) -> list[str]:
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
                email = node.get("email")
                if isinstance(email, str):
                    found.append(email)
                elif isinstance(email, list):
                    found.extend(str(e) for e in email)
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    return found


def extract_emails_from_html(html: str) -> list[str]:
    """Collect normalized emails from HTML, best-first order."""
    candidates: list[str] = []

    for m in _MAILTO_RE.findall(html):
        candidates.append(m)
    for m in _DATA_EMAIL_RE.findall(html):
        candidates.append(m)
    for m in _ITEMPROP_EMAIL_RE.findall(html):
        candidates.append(m)
    for m in _META_EMAIL_RE.findall(html):
        candidates.append(m)
    candidates.extend(_emails_from_json_ld(html))
    for m in _EMAIL_RE.findall(html[:120_000]):
        candidates.append(m)

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in candidates:
        norm = _normalize_email(raw)
        if norm and norm not in seen:
            seen.add(norm)
            ordered.append(norm)
    return ordered


def extract_primary_email(html: str) -> str | None:
    emails = extract_emails_from_html(html)
    return emails[0] if emails else None
