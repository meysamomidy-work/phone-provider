"""Extract general and staff email addresses from dealership website HTML.

The normal website-enrichment flow uses :func:`extract_primary_email`.  The
staff-email pass additionally uses :func:`find_staff_page_urls` to select a
small set of likely contact/team pages, then stores records from
:func:`extract_staff_email_records` as JSON.  The parsing deliberately relies
only on the standard library so it also works in the project's lightweight
HTTP-only setup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote, urldefrag, urljoin, urlparse

_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_EMAIL_RE = re.compile(
    r"\b([a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,})\b"
)
_OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([a-zA-Z0-9][a-zA-Z0-9._%+-]*)\s*"
    r"(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\})\s*"
    r"([a-zA-Z0-9-]+(?:\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\bdot\b|\.)\s*"
    r"[a-zA-Z0-9-]+)+)\b",
    re.I,
)
_CF_EMAIL_RE = re.compile(r"data-cfemail\s*=\s*['\"]([0-9a-f]+)['\"]", re.I)

_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_PERSON_CONTAINER_RE = re.compile(
    r"(?:staff|team|employee|people|person|profile|bio|member|associate|advisor|consultant|"
    r"leadership|management|manager|director|salesperson|sales-rep|representative)",
    re.I,
)
_PERSON_ACTION_RE = re.compile(r"(?:action|button|email|contact|social|share|modal|link)", re.I)
# Do not treat a whole ``staff-card`` / ``team-member`` container as a name;
# the name normally lives in a descendant heading or a more specific *-name
# element.  Broad person-card labels are handled by the heading fallback.
_NAME_HINT_RE = re.compile(r"(?:name|full[-_ ]?name)", re.I)
_ROLE_HINT_RE = re.compile(
    r"(?:job[-_ ]?title|position|designation|role|title|department|job|rank)", re.I
)
_STAFF_LINK_RE = re.compile(
    r"(?:contact(?:[-_ ]?us)?|staff|our[-_ ]?team|meet[-_ ]?(?:the[-_ ]?)?(?:team|staff)|"
    r"team|people|bios?|leadership|management|directory|employees?|associates?|our[-_ ]?people|"
    r"who[-_ ]?we[-_ ]?are|about[-_ ]?us|dealership[-_ ]?team|meet[-_ ]?our)",
    re.I,
)
_NON_PAGE_SUFFIX_RE = re.compile(r"\.(?:pdf|jpg|jpeg|png|gif|webp|svg|zip|mp4|css|js)(?:$|[?#])", re.I)
_NON_VISIBLE_EMAIL_TAGS = frozenset({"script", "style", "template", "noscript", "svg", "code", "pre"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"})
_BUSINESS_SCHEMA_TYPES = frozenset({"organization", "localbusiness", "autodealer", "automotivebusiness", "contactpoint"})

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

_BLOCKED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def _normalize_email(raw: str) -> str | None:
    """Return a safe canonical email address, or ``None`` for placeholders."""
    if not raw:
        return None
    text = unquote(unescape(raw)).strip().lower()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    text = text.split("?", 1)[0].strip()
    if not text or "@" not in text:
        return None
    if any(text.endswith(s) for s in _BLOCKED_SUFFIXES):
        return None

    local, _, domain = text.rpartition("@")
    domain = domain.rstrip(".")
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


def _decode_cloudflare_email(value: str) -> str | None:
    """Decode Cloudflare's public ``data-cfemail`` obfuscation attribute."""
    try:
        data = bytes.fromhex(value)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    key = data[0]
    return "".join(chr(byte ^ key) for byte in data[1:])


def _obfuscated_email_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for local, domain in _OBFUSCATED_EMAIL_RE.findall(unescape(text or "")):
        normalized_domain = re.sub(
            r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\bdot\b)\s*",
            ".",
            domain,
            flags=re.I,
        )
        candidates.append(f"{local}@{normalized_domain.replace(' ', '')}")
    return candidates


def _email_candidates(text: str) -> list[str]:
    """Extract direct, encoded, and common human-readable obfuscated emails."""
    value = unescape(text or "")
    candidates = _EMAIL_RE.findall(value)
    candidates.extend(_obfuscated_email_candidates(value))
    for encoded in _CF_EMAIL_RE.findall(value):
        decoded = _decode_cloudflare_email(encoded)
        if decoded:
            candidates.append(decoded)
    return candidates


def _emails_from_json_ld(html: str) -> list[str]:
    found: list[str] = []
    for block in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(unescape(block.strip()))
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
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return found


def extract_emails_from_html(html: str) -> list[str]:
    """Collect normalized public emails, excluding script/build-package text."""
    dom_candidates = _visible_dom_email_candidates(html)
    candidates: list[str] = []
    candidates.extend(dom_candidates["mailto"])
    candidates.extend(dom_candidates["data"])
    candidates.extend(dom_candidates["itemprop"])
    candidates.extend(dom_candidates["meta"])
    candidates.extend(_emails_from_json_ld(html))
    candidates.extend(dom_candidates["text"])

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in candidates:
        normalized = _normalize_email(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def extract_primary_email(html: str) -> str | None:
    emails = extract_emails_from_html(html)
    return emails[0] if emails else None


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    parent: "_HtmlNode | None" = None
    children: list["_HtmlNode"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        values = [*self.text_parts]
        for child in self.children:
            values.append(child.text())
        return _clean_text(" ".join(values))

    def attr_text(self) -> str:
        return " ".join(f"{key} {value}" for key, value in self.attrs.items())


class _TreeParser(HTMLParser):
    """Tolerant enough HTML tree for finding email-card context."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("document", {})
        self.nodes: list[_HtmlNode] = [self.root]
        self._stack: list[_HtmlNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlNode(tag.lower(), {key.lower(): value or "" for key, value in attrs}, self._stack[-1])
        self._stack[-1].children.append(node)
        self.nodes.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for position in range(len(self._stack) - 1, 0, -1):
            if self._stack[position].tag == tag:
                del self._stack[position:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].text_parts.append(data)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _node_and_ancestors(node: _HtmlNode) -> list[_HtmlNode]:
    result: list[_HtmlNode] = []
    current: _HtmlNode | None = node
    while current is not None:
        result.append(current)
        current = current.parent
    return result


def _is_person_container(node: _HtmlNode) -> bool:
    attributes = node.attr_text()
    return bool(_PERSON_CONTAINER_RE.search(attributes)) and not bool(_PERSON_ACTION_RE.search(attributes))


def _has_non_visible_ancestor(node: _HtmlNode) -> bool:
    return any(candidate.tag in _NON_VISIBLE_EMAIL_TAGS for candidate in _node_and_ancestors(node))


def _visible_node_text(node: _HtmlNode) -> str:
    """Text rendered to a visitor, without script/template/style descendants."""
    if node.tag in _NON_VISIBLE_EMAIL_TAGS:
        return ""
    values = [*node.text_parts]
    for child in node.children:
        values.append(_visible_node_text(child))
    return _clean_text(" ".join(values))


def _visible_dom_email_candidates(html: str) -> dict[str, list[str]]:
    """Read actual DOM attributes/visible text, never raw JavaScript bundles."""
    result = {"mailto": [], "data": [], "itemprop": [], "meta": [], "text": []}
    parser = _TreeParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return result

    for node in parser.nodes:
        if _has_non_visible_ancestor(node):
            continue
        href = node.attrs.get("href", "")
        if href.lower().startswith("mailto:"):
            result["mailto"].append(href)
        for key in ("data-email", "data-e-mail", "data-mail"):
            if value := node.attrs.get(key):
                result["data"].extend(_email_candidates(value))
        if encoded := node.attrs.get("data-cfemail"):
            decoded = _decode_cloudflare_email(encoded)
            if decoded:
                result["data"].append(decoded)
        if node.attrs.get("itemprop", "").lower() == "email":
            result["itemprop"].extend(_email_candidates(_visible_node_text(node)))
        if node.tag == "meta" and node.attrs.get("name", node.attrs.get("property", "")).lower() in {"og:email", "email"}:
            result["meta"].extend(_email_candidates(node.attrs.get("content", "")))
        result["text"].extend(_email_candidates(" ".join(node.text_parts)))
        if node.tag in {"a", "p", "span", "div", "li", "article", "address", "section"}:
            node_text = _visible_node_text(node)
            if len(node_text) <= 2_000:
                result["text"].extend(_email_candidates(node_text))
    return result


def _context_node(node: _HtmlNode) -> tuple[_HtmlNode, bool]:
    """Choose the closest small card that actually contains staff-like markup."""
    ancestors = _node_and_ancestors(node)
    best: tuple[int, _HtmlNode, bool] | None = None
    for position, candidate in enumerate(ancestors[1:], start=1):
        if candidate.tag == "document":
            continue
        text_length = len(_visible_node_text(candidate))
        is_person = _is_person_container(candidate)
        max_length = 2_000 if is_person else 700
        if text_length > max_length:
            continue
        has_heading = any(child.tag in _HEADING_TAGS for child in _descendants(candidate))
        if not (is_person or has_heading):
            continue
        # A normal <li>/<article> with H3/H4 staff data is a valid card even
        # when a CMS gives it a generic class.  This is the markup used by
        # Dealer Inspire (including Kendall Toyota of Anchorage).
        score = 20 if is_person else 0
        score += 8 if has_heading else 0
        score += 3 if candidate.tag in {"li", "article", "address"} else 1
        score += max(0, 4 - position)  # prefer the nearest qualifying card
        if best is None or score > best[0]:
            best = (score, candidate, is_person or has_heading)
    if best is not None:
        return best[1], best[2]
    for candidate in ancestors[1:4]:
        if candidate.tag in {"li", "article", "address", "p", "div", "section"} and len(_visible_node_text(candidate)) <= 700:
            return candidate, False
    return node, False


def _descendants(node: _HtmlNode) -> list[_HtmlNode]:
    output: list[_HtmlNode] = []
    stack = list(reversed(node.children))
    while stack:
        child = stack.pop()
        output.append(child)
        stack.extend(reversed(child.children))
    return output


def _probably_name(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"\b(?:email|contact|call|phone|tel)\b.*$", "", text, flags=re.I).strip(" -|:")
    if not text or "@" in text or len(text) > 90 or re.search(r"\d{3,}", text):
        return ""
    words = text.split()
    if not 2 <= len(words) <= 6:
        return ""
    if any(word.lower() in {
        "contact", "email", "sales", "service", "department", "team", "staff",
        "hours", "location", "dealership", "search", "vehicles", "total",
        "price", "feedback", "comments", "welcome", "keyword", "inventory",
        "dealer", "info", "we", "your",
    } for word in words):
        return ""
    if text.lower() in {"coming soon", "learn more", "read more", "call us", "about us", "get directions", "our inventory"}:
        return ""
    if re.search(r"\b(?:first name|last name|full name|your name)\b", text, re.I):
        return ""
    if re.search(r"\b(?:car|auto|motor|vehicle)\s+(?:center|centre|sales|group|dealership)\b", text, re.I):
        return ""
    if not any(any(ch.isalpha() for ch in word) for word in words):
        return ""
    return text


_INFERRED_JOB_WORD_RE = re.compile(
    r"\b(?:manager|director|consultant|advisor|principal|coordinator|specialist|"
    r"technician|associate|president|owner|executive|representative|lead|agent|"
    r"sales|finance|service|parts|internet|business|accountant|receptionist|"
    r"administrator|controller|buyer|detailer|mechanic|porter|operations|marketing)\b",
    re.I,
)


def _probably_role(value: str, *, inferred: bool = False) -> str:
    text = _clean_text(value).strip(" -|:")
    if not text or "@" in text or len(text) > 120 or re.search(r"\d{4,}", text):
        return ""
    if re.search(r"\b(?:email|contact|phone|tel|directions|hours|our location|dealership info|our staff|coming soon)\b", text, re.I):
        return ""
    if re.search(r"\b(?:car|auto|motor|vehicle)\s+(?:center|centre|sales|group|dealership)\b", text, re.I):
        return ""
    if inferred and not _INFERRED_JOB_WORD_RE.search(text):
        return ""
    return text


def _has_role_hint(node: _HtmlNode) -> bool:
    """Recognize role/title fields without mistaking ARIA ``role`` for a job."""
    attributes = " ".join(
        f"{key} {value}"
        for key, value in node.attrs.items()
        if key != "role"
    )
    return bool(_ROLE_HINT_RE.search(attributes))


def _staff_metadata(node: _HtmlNode) -> tuple[str, str]:
    """Infer a card's name and role from semantic attributes/headings."""
    # Global chrome commonly has a dealership-name heading and an hours block
    # beside a footer email. They are not the mailbox owner's name/job title.
    if any(parent.tag in {"footer", "header", "nav"} for parent in _node_and_ancestors(node)):
        return "", ""
    context, is_person_card = _context_node(node)
    candidates = [context, *_descendants(context)]
    name = _probably_name(
        node.attrs.get("data-staff-name")
        or node.attrs.get("data-employee-name")
        or node.attrs.get("data-person-name")
        or ""
    )
    role = _probably_role(
        node.attrs.get("data-staff-title")
        or node.attrs.get("data-job-title")
        or node.attrs.get("data-position")
        or ""
    )
    headings: list[tuple[str, str]] = []
    for candidate in candidates:
        text = _visible_node_text(candidate)
        attrs = candidate.attr_text()
        if not name and (
            candidate.tag in _HEADING_TAGS
            or _NAME_HINT_RE.search(attrs)
            or candidate.attrs.get("itemprop", "").lower() == "name"
        ):
            name = _probably_name(text)
        if not role and (
            _has_role_hint(candidate)
            or candidate.attrs.get("itemprop", "").lower() in {"jobtitle", "role"}
        ):
            role = _probably_role(text)
        if candidate.tag in _HEADING_TAGS:
            heading = _clean_text(text)
            if heading and len(heading) <= 120:
                headings.append((candidate.tag, heading))

    # Many cards use an unlabelled H3 for a name followed by a short paragraph
    # for the title. Do this only when the surrounding element looks like staff.
    if is_person_card and not name:
        for _, heading in headings:
            name = _probably_name(heading)
            if name:
                break
    # Some dealer platforms use an H3 followed by an H4 rather than classes
    # such as `job-title`; use the following heading as the role.
    if is_person_card and not role and name:
        for tag, heading in headings:
            if tag in {"strong", "b"} or heading == name:
                continue
            possible = _probably_role(heading, inferred=True)
            if possible:
                role = possible
                break
    if is_person_card and not role and name:
        for candidate in _descendants(context):
            if candidate.tag not in {"p", "span", "div", "small"}:
                continue
            possible = _probably_role(candidate.text(), inferred=True)
            if possible and possible != name:
                role = possible
                break
    if is_person_card and not role and name:
        full_text = _visible_node_text(context)
        remainder = _clean_text(full_text.replace(name, "", 1))
        for part in re.split(r"[|•\n]", remainder):
            possible = _probably_role(part, inferred=True)
            if possible and possible != name:
                role = possible
                break
    if not name:
        role = ""
    return name, role


def _json_ld_staff_records(html: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for block in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(unescape(block.strip()))
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                raw_email = node.get("email")
                types = node.get("@type", "")
                type_values = types if isinstance(types, list) else [types]
                schema_types = {str(value).replace(" ", "").lower() for value in type_values}
                looks_like_person = "person" in schema_types
                is_business_contact = bool(schema_types & _BUSINESS_SCHEMA_TYPES)
                if raw_email and (looks_like_person or is_business_contact):
                    emails = raw_email if isinstance(raw_email, list) else [raw_email]
                    for raw in emails:
                        email = _normalize_email(str(raw))
                        if email:
                            records.append(
                                {
                                    "email": email,
                                    "name": _clean_text(str(node.get("name", ""))) if looks_like_person else "",
                                    "role": _clean_text(str(node.get("jobTitle") or node.get("role") or "")) if looks_like_person else "",
                                }
                            )
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return records


def _merge_staff_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Deduplicate by email while retaining the richest discovered context."""
    by_email: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for raw in records:
        email = _normalize_email(raw.get("email", ""))
        if not email:
            continue
        record = {
            "email": email,
            "name": _clean_text(raw.get("name", "")),
            "role": _clean_text(raw.get("role", "")),
        }
        existing = by_email.get(email)
        if existing is None:
            by_email[email] = record
            order.append(email)
            continue
        # A named record on a team page is more valuable than the same mailbox
        # found in a global site footer.
        for field in ("name", "role"):
            if not existing[field] and record[field]:
                existing[field] = record[field]
    return [by_email[email] for email in order]


def merge_staff_email_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge staff-email records from multiple dealer pages by email address."""
    return _merge_staff_records(records)


def extract_staff_email_records(html: str) -> list[dict[str, str]]:
    """Return public email records with inferred name and role.

    The function intentionally keeps public department or contact mailboxes too:
    a dealer may expose no individual names, but those addresses are still useful
    contacts and can be revisited later as pages change.
    """
    parser = _TreeParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        # HTMLParser is very forgiving; this simply preserves regex extraction
        # if a malformed response still manages to upset it.
        pass

    records = _json_ld_staff_records(html)
    for node in parser.nodes:
        # Bundled React code, vendor scripts, source maps, and style/template
        # data routinely contain example/support addresses. They are not
        # dealer contacts, so only rendered markup contributes here. JSON-LD
        # Person/business records are handled separately above.
        if _has_non_visible_ancestor(node):
            continue
        candidates: list[str] = []
        for key, value in node.attrs.items():
            if key in {"data-email", "data-e-mail", "data-mail", "data-cfemail"}:
                if key == "data-cfemail":
                    decoded = _decode_cloudflare_email(value)
                    if decoded:
                        candidates.append(decoded)
                else:
                    candidates.extend(_email_candidates(value))
            elif key == "href" and value.lower().startswith("mailto:"):
                candidates.append(value)
        candidates.extend(_email_candidates(" ".join(node.text_parts)))
        # This also captures visible addresses split by nested <span> tags.
        if node.tag in {"a", "p", "span", "div", "li", "article", "address", "section"}:
            node_text = _visible_node_text(node)
            if len(node_text) <= 2_000:
                candidates.extend(_email_candidates(node_text))
        if not candidates:
            continue
        name, role = _staff_metadata(node)
        for raw in candidates:
            email = _normalize_email(raw)
            if email:
                records.append({"email": email, "name": name, "role": role})
    return _merge_staff_records(records)


def _site_host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0].removeprefix("www.")


def find_staff_page_urls(html: str, base_url: str, *, limit: int = 8) -> list[str]:
    """Find same-site contact, staff, team, and leadership pages from a home page.

    Links are ranked rather than relying on one exact URL naming convention.
    The bounded result avoids turning a dealer enrichment into an uncontrolled
    crawl while still covering common `contact`, `meet-the-team`, `staff`, and
    `directory` structures.
    """
    if limit <= 0:
        return []
    base_host = _site_host(base_url)
    scored: dict[str, int] = {}
    for match in re.finditer(r"<a\b([^>]*?)>(.*?)</a\s*>", html or "", re.I | re.S):
        attributes, inner = match.groups()
        href_match = re.search(r"\bhref\s*=\s*['\"]([^'\"]+)", attributes, re.I)
        if not href_match:
            continue
        href = unescape(href_match.group(1)).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute, _ = urldefrag(urljoin(base_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or _site_host(absolute) != base_host:
            continue
        if _NON_PAGE_SUFFIX_RE.search(absolute):
            continue
        label = _clean_text(re.sub(r"<[^>]+>", " ", inner))
        attributes_text = _clean_text(re.sub(r"\s+", " ", attributes))
        haystack = f"{parsed.path} {parsed.query} {label} {attributes_text}".lower()
        if not _STAFF_LINK_RE.search(haystack):
            continue
        score = 0
        if re.search(r"staff|team|meet|bio|leadership|management|directory|people|employee|associate", haystack, re.I):
            score += 4
        if re.search(r"contact", haystack, re.I):
            score += 3
        if re.search(r"about|who.we.are", haystack, re.I):
            score += 1
        if label:
            score += 1
        canonical = parsed._replace(fragment="").geturl()
        scored[canonical] = max(scored.get(canonical, 0), score)
    return [url for url, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:limit]]
