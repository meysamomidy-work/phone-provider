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
_BLOCKED_VENDOR_EXACT_DOMAINS = frozenset({
    "dealerinspire.com", "dealeron.com", "carsforsale.com",
    "intice.com", "edealerhub.com", "eautodealerhub.com",
})

_BLOCKED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_VALID_EMAIL_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9._%+-]*[a-z0-9])?@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
    re.I,
)
_PROSE_DOMAIN_ENDINGS = frozenset({
    # These are sentence fragments seen after an @ sign in rendered dealer
    # pages, not usable mail domains. Keep this narrow: uncommon real TLDs
    # are otherwise allowed, especially for explicit mailto links.
    "again", "allen", "and", "apply", "bring", "brought", "cim",
    "dohmann", "everyone", "fill", "great", "he", "if", "job", "left",
    "located", "mandeville", "on", "our", "ponchatoula", "she", "son",
    "that", "these", "they", "told", "two", "upon", "used", "we",
    "we", "whether", "with",
})
_PROSE_SECOND_LEVEL = frozenset({
    "0", "all", "com", "home", "it", "legacy", "net", "online",
    "org", "our", "the", "you",
})
_PROSE_AMBIGUOUS_ENDINGS = frozenset({"as", "by", "it", "my", "you"})
_GENERIC_NAME_RE = re.compile(
    r"^(?:how to reach us|select primary|review us|new inventory|store hours|"
    r"search vehicles|total price|browse through our inventory|used vehicles|"
    r"we welcome your feedback and comments|contact us|learn more|read more|"
    r"how to|address\s*&|make an inquiry|leave a message below|"
    r"your options regarding marketing communications|translate website|"
    r"business hours|about\b.*|meet (?:the|our) staff\b.*|"
    r"privacy policy|job openings|"
    r"have additional questions\??|how to purchase online|"
    r"welcome to our dealership!?|first name(?: last name)?\s*\*?)$",
    re.I,
)
_GENERIC_ROLE_RE = re.compile(
    r"(?:\bhours\b|\brequired field\b|\bhow to reach us\b|\bsearch by keyword\b|"
    r"\bmeet (?:the|our) staff\b|\bprivacy policy\b|\bjob openings\b|"
    r"\bapply for position\b|\bget in touch\b)",
    re.I,
)


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
    if not _VALID_EMAIL_RE.fullmatch(text):
        return None
    if ".." in text:
        return None
    if any(text.endswith(s) for s in _BLOCKED_SUFFIXES):
        return None

    local, _, domain = text.rpartition("@")
    domain = domain.rstrip(".")
    if not local or not domain or "." not in domain:
        return None
    if domain in _BLOCKED_DOMAINS or domain in _BLOCKED_VENDOR_EXACT_DOMAINS:
        return None
    if any(domain.endswith(f".{blocked}") for blocked in _BLOCKED_DOMAINS):
        return None
    labels = domain.split(".")
    if not re.fullmatch(r"[a-z]{2,63}", labels[-1]):
        return None
    if any(
        len(re.sub(r"\D", "", label)) >= 6 and re.fullmatch(r"\d+(?:-\d+)+", label)
        for label in labels[:-1]
    ):
        return None
    if labels[-1] in _PROSE_DOMAIN_ENDINGS:
        return None
    if labels[-1] in _PROSE_AMBIGUOUS_ENDINGS and labels[-2] in _PROSE_SECOND_LEVEL:
        return None

    local_base = local.split("+", 1)[0]
    if local_base in _INVALID_LOCAL_PARTS:
        return None
    if len(local) > 64 or len(domain) > 255:
        return None
    return f"{local}@{domain}"


def _name_matches_email(name: str, email: str) -> bool:
    """Use a mailbox's local part only to disambiguate repeated names."""
    words = re.findall(r"[a-z]+", name.casefold())
    if len(words) < 2:
        return False
    first, last = words[0], words[-1]
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].split("+", 1)[0].casefold())
    return bool(
        local == first and len(first) >= 3
        or last in local and (first in local or local.startswith(first[:1] + last) or local == last)
    )


def _is_department_list(value: str) -> bool:
    words = re.findall(r"[a-z]+", value.casefold())
    return bool(
        len(words) >= 3 and len(set(words)) >= 2
        and set(words) <= {
            "management", "sales", "service", "parts", "office",
            "department", "staff", "team", "customer",
        }
    )


def clean_staff_email_records(value: str, dealer_name: str = "") -> tuple[str, int, int]:
    """Conservatively clean prior JSON without discarding plausible contacts.

    Returns serialized JSON plus counts of rejected addresses and cleared
    metadata fields. Non-JSON values are left untouched for review.
    """
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value, 0, 0
    if not isinstance(parsed, list):
        return value, 0, 0
    cleaned: list[object] = []
    removed = 0
    cleared = 0
    changed = False
    seen: set[str] = set()
    dealer_label = re.sub(r"[^a-z0-9]+", "", dealer_name.casefold())
    for entry in parsed:
        if not isinstance(entry, dict):
            cleaned.append(entry)
            continue
        item = {key: field_value for key, field_value in entry.items() if key != "source_url"}
        changed |= len(item) != len(entry)
        email = _normalize_email(str(item.get("email", "")))
        if not email:
            removed += 1
            changed = True
            continue
        if email in seen:
            removed += 1
            changed = True
            continue
        seen.add(email)
        if item.get("email") != email:
            item["email"] = email
            changed = True
        name = _clean_text(str(item.get("name", "")))
        role = _clean_text(str(item.get("role", "")))
        name_label = re.sub(r"[^a-z0-9]+", "", name.casefold())
        is_dealer_heading = bool(
            dealer_label and name_label == dealer_label
            and email.split("@", 1)[0] in {
                "info", "sales", "contact", "contactus", "hello", "office",
                "support", "service", "parts", "general",
            }
        )
        if name and (_GENERIC_NAME_RE.fullmatch(name) or is_dealer_heading):
            item["name"] = ""
            cleared += 1
            changed = True
            name = ""
        if role and (
            _GENERIC_ROLE_RE.search(role)
            or _is_department_list(role)
            or not name and _GENERIC_NAME_RE.fullmatch(_clean_text(str(entry.get("name", ""))))
            or not name and is_dealer_heading
            or name and role.casefold() == name.casefold()
        ):
            item["role"] = ""
            cleared += 1
            changed = True
        cleaned.append(item)
    # A broad staff-list wrapper can make one employee's name appear as the
    # role on another employee's record. Do not preserve that as a job title.
    known_names = {
        _clean_text(str(item.get("name", ""))).casefold()
        for item in cleaned if isinstance(item, dict) and item.get("name")
    }
    for item in cleaned:
        if not isinstance(item, dict):
            continue
        role = _clean_text(str(item.get("role", "")))
        if role and role.casefold() in known_names and _probably_name(role):
            item["role"] = ""
            cleared += 1
            changed = True
    repeated_names: dict[str, list[dict[str, str]]] = {}
    repeated_roles: dict[str, list[dict[str, str]]] = {}
    for item in cleaned:
        if not isinstance(item, dict):
            continue
        if name := _clean_text(str(item.get("name", ""))):
            repeated_names.setdefault(name.casefold(), []).append(item)
        if role := _clean_text(str(item.get("role", ""))):
            repeated_roles.setdefault(role.casefold(), []).append(item)
    for group in repeated_names.values():
        if len(group) < 3:
            continue
        for item in group:
            if not _name_matches_email(str(item["name"]), str(item["email"])):
                item["name"] = ""
                cleared += 1
                changed = True
    for group in repeated_roles.values():
        if len(group) < 3:
            continue
        role = _clean_text(str(group[0]["role"]))
        words = role.split()
        if len(words) < 3:
            continue
        possible_name = " ".join(words[:2])
        actual_role = " ".join(words[2:])
        if not _probably_name(possible_name) or not _probably_role(actual_role, inferred=True):
            continue
        matches = [item for item in group if _name_matches_email(possible_name, str(item["email"]))]
        if len(matches) > 1:
            continue
        for item in group:
            if matches and item is matches[0]:
                if not item.get("name"):
                    item["name"] = possible_name
                    cleared += 1
                    changed = True
                if item["role"] != actual_role:
                    item["role"] = actual_role
                    cleared += 1
                    changed = True
            elif item.get("role"):
                item["role"] = ""
                cleared += 1
                changed = True
    if not changed:
        return value, removed, cleared
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")), removed, cleared


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
        probable_names = {
            name for child in _descendants(candidate)
            if child.tag in _HEADING_TAGS
            if (name := _probably_name(_visible_node_text(child)))
        }
        score = 20 if is_person else 0
        score += 8 if has_heading else 0
        score += 8 if candidate.tag in {"li", "article", "address"} else 1
        score += max(0, 4 - position)  # prefer the nearest qualifying card
        score -= 15 * max(0, len(probable_names) - 1)
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
    if _GENERIC_NAME_RE.fullmatch(text):
        return ""
    words = text.split()
    if not 2 <= len(words) <= 6:
        return ""
    if any(word.lower() in {
        "contact", "email", "sales", "service", "department", "team", "staff",
        "hours", "location", "dealership", "search", "vehicles", "total",
        "feedback", "comments", "welcome", "keyword", "inventory",
        "dealer", "info", "we", "your",
        "manager", "director", "consultant", "advisor", "owner", "president",
        "specialist", "policy", "privacy", "about", "openings", "questions",
        "car", "auto", "new", "used", "leasing", "and", "&",
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
    if _GENERIC_ROLE_RE.search(text):
        return ""
    if _is_department_list(text):
        return ""
    if re.search(r"\b(?:email|contact|phone|tel|directions|hours|our location|dealership info|our staff|coming soon)\b", text, re.I):
        return ""
    if re.search(r"\b(?:car|auto|motor|vehicle)\s+(?:center|centre|sales|group|dealership)\b", text, re.I) and not re.search(
        r"\b(?:manager|consultant|advisor|director|specialist|associate|representative)\b", text, re.I
    ):
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
            possible_role = _probably_role(text)
            if possible_role.casefold() != name.casefold():
                role = possible_role
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
    if name and role.casefold() == name.casefold():
        role = ""
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


@dataclass(frozen=True)
class StaffPageSignals:
    named_staff: int = 0
    empty_listing: bool = False
    contact_form: bool = False


_EMPTY_STAFF_RE = re.compile(
    r"(?:no staff members listed|no staff found|no team members listed|"
    r"no employees listed|staff information (?:is )?unavailable)",
    re.I,
)


def inspect_staff_page(html: str) -> StaffPageSignals:
    """Find evidence of actual staff content, not merely a staff-shaped URL."""
    parser = _TreeParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return StaffPageSignals()
    visible = _visible_node_text(parser.root)
    empty_listing = bool(_EMPTY_STAFF_RE.search(visible))
    contact_form = False
    names: set[str] = set()
    for node in parser.nodes:
        if _has_non_visible_ancestor(node):
            continue
        if node.tag == "form":
            fields = _descendants(node)
            has_email = any(
                child.tag == "input"
                and (child.attrs.get("type", "").lower() == "email" or "email" in child.attrs.get("name", "").lower())
                for child in fields
            )
            has_contact_fields = any(
                child.tag == "textarea" or child.tag == "input" and re.search(
                    r"(?:name|phone|message|comment)", child.attrs.get("name", "") + " " + child.attrs.get("id", ""), re.I
                )
                for child in fields
            )
            contact_form |= has_email and has_contact_fields
        if node.tag not in {"li", "article", "div", "section"}:
            continue
        is_card = _is_person_container(node)
        if not is_card and node.tag not in {"li", "article"}:
            continue
        if len(_visible_node_text(node)) > 1_200:
            continue
        headings = [child for child in _descendants(node) if child.tag in _HEADING_TAGS]
        if not is_card and node.tag in {"li", "article"}:
            is_card = any(_probably_role(_visible_node_text(child), inferred=True) for child in headings)
        if not is_card:
            continue
        for child in _descendants(node):
            if child.tag in _HEADING_TAGS or _NAME_HINT_RE.search(child.attr_text()):
                if name := _probably_name(_visible_node_text(child)):
                    names.add(name)
    return StaffPageSignals(len(names), empty_listing, contact_form)


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
