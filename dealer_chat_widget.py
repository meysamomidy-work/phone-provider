"""Detect third-party chat widgets on dealer websites."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Order preserved: first match wins when reporting a single best; all matches are joined.
CHAT_WIDGET_COMPETITORS: tuple[str, ...] = (
    "hammer",
    "gubagoo",
    "podium",
    "carnow",
    "dealerai",
    "drivee_ai",
    "matador",
    "tecobi",
    "spyne",
    "kenect",
    "rybo",
    "toma",
    "numa",
    "impel",
    "drivecentric",
    "autoalert",
    "selly_automotive",
    "sandra_ai",
    "autofi",
    "activengage",
    "contact_at_once",
    "carchat24",
    "livechat",
    "intercom",
    "zendesk",
    "drift",
    "conversica",
    "autoconverse",
    "carbuddy",
    "chatbeacon",
    "dealerbot",
)

_DISPLAY_NAMES: dict[str, str] = {
    "hammer": "Hammer",
    "gubagoo": "Gubagoo",
    "podium": "Podium",
    "carnow": "CarNow",
    "dealerai": "DealerAI",
    "drivee_ai": "Drivee.ai",
    "matador": "Matador",
    "tecobi": "Tecobi",
    "spyne": "Spyne",
    "kenect": "Kenect",
    "rybo": "Rybo",
    "toma": "Toma",
    "numa": "Numa",
    "impel": "Impel",
    "drivecentric": "DriveCentric",
    "autoalert": "AutoAlert",
    "selly_automotive": "Selly Automotive",
    "sandra_ai": "Sandra AI",
    "autofi": "AutoFi",
    "activengage": "ActivEngage",
    "contact_at_once": "Contact At Once",
    "carchat24": "CarChat24",
    "livechat": "LiveChat",
    "intercom": "Intercom",
    "zendesk": "Zendesk",
    "drift": "Drift",
    "conversica": "Conversica",
    "autoconverse": "AutoConverse",
    "carbuddy": "CarBuddy",
    "chatbeacon": "ChatBeacon",
    "dealerbot": "Dealerbot",
}


@dataclass(frozen=True, slots=True)
class _ChatWidgetRule:
    provider_id: str
    html_substrings: tuple[str, ...]
    html_regexes: tuple[str, ...]
    host_regexes: tuple[str, ...]


_RULES: tuple[_ChatWidgetRule, ...] = (
    _ChatWidgetRule(
        "hammer",
        ("hammer.ai", "hammercorp", "hammer chat", "usehammer"),
        (r"hammer\.ai", r"cdn\.hammer\.ai", r"app\.hammer\.ai"),
        (r"^.*\.hammer\.ai$",),
    ),
    _ChatWidgetRule(
        "gubagoo",
        ("gubagoo.com", "gubagoo chat", "powered by gubagoo"),
        (r"gubagoo\.com", r"cdn\.gubagoo\.com", r"widget\.gubagoo\.com"),
        (r"^.*\.gubagoo\.com$",),
    ),
    _ChatWidgetRule(
        "podium",
        ("podium.com", "podium chat", "podium-widget"),
        (r"podium\.com", r"cdn\.podium\.com", r"widget\.podium\.com"),
        (r"^.*\.podium\.com$",),
    ),
    _ChatWidgetRule(
        "carnow",
        ("carnow.com", "carnow chat", "carnow widget"),
        (r"carnow\.com", r"cdn\.carnow\.com", r"widget\.carnow\.com"),
        (r"^.*\.carnow\.com$",),
    ),
    _ChatWidgetRule(
        "dealerai",
        ("dealerai.com", "dealer ai chat"),
        (r"dealerai\.com", r"cdn\.dealerai\.com", r"app\.dealerai\.com"),
        (r"^.*\.dealerai\.com$",),
    ),
    _ChatWidgetRule(
        "drivee_ai",
        (
            "drivee.ai",
            "salesagent-widget.web.app",
            "salesagent-widget-iframe",
            "salesagentwidget",
        ),
        (
            r"drivee\.ai",
            r"salesagent-widget\.web\.app",
            r"salesagent-widget-iframe",
            r"salesagentwidget",
        ),
        (r"^salesagent-widget\.web\.app$", r"^.*\.drivee\.ai$"),
    ),
    _ChatWidgetRule(
        "matador",
        ("matador.ai", "matador chat", "matador automotive"),
        (r"matador\.ai", r"cdn\.matador\.ai", r"app\.matador\.ai"),
        (r"^.*\.matador\.ai$",),
    ),
    _ChatWidgetRule(
        "tecobi",
        ("tecobi.com", "tecobi chat"),
        (r"tecobi\.com", r"cdn\.tecobi\.com", r"widget\.tecobi\.com"),
        (r"^.*\.tecobi\.com$",),
    ),
    _ChatWidgetRule(
        "spyne",
        ("spyne.ai", "spyne chat", "spyne automotive"),
        (r"spyne\.ai", r"cdn\.spyne\.ai", r"app\.spyne\.ai"),
        (r"^.*\.spyne\.ai$",),
    ),
    _ChatWidgetRule(
        "kenect",
        ("kenect.com", "kenect chat"),
        (r"kenect\.com", r"cdn\.kenect\.com", r"widget\.kenect\.com"),
        (r"^.*\.kenect\.com$",),
    ),
    _ChatWidgetRule(
        "rybo",
        ("rybo.ai", "rybo chat"),
        (r"rybo\.ai", r"cdn\.rybo\.ai", r"app\.rybo\.ai"),
        (r"^.*\.rybo\.ai$",),
    ),
    _ChatWidgetRule(
        "toma",
        ("toma.com", "toma chat", "toma automotive"),
        (r"toma\.com", r"cdn\.toma\.com", r"widget\.toma\.com"),
        (r"^.*\.toma\.com$",),
    ),
    _ChatWidgetRule(
        "numa",
        ("numa.com", "numa chat", "numa automotive"),
        (r"numa\.com", r"cdn\.numa\.com", r"app\.numa\.com"),
        (r"^.*\.numa\.com$",),
    ),
    _ChatWidgetRule(
        "impel",
        ("impel.io", "impel.ai", "impel chat", "formerly spin"),
        (r"impel\.io", r"impel\.ai", r"cdn\.impel\.io"),
        (r"^.*\.impel\.io$", r"^.*\.impel\.ai$"),
    ),
    _ChatWidgetRule(
        "drivecentric",
        ("drivecentric.com", "drive centric"),
        (r"drivecentric\.com", r"cdn\.drivecentric\.com"),
        (r"^.*\.drivecentric\.com$",),
    ),
    _ChatWidgetRule(
        "autoalert",
        ("autoalert.com", "auto alert chat"),
        (r"autoalert\.com", r"cdn\.autoalert\.com"),
        (r"^.*\.autoalert\.com$",),
    ),
    _ChatWidgetRule(
        "selly_automotive",
        ("sellyautomotive.com", "selly automotive"),
        (r"sellyautomotive\.com", r"cdn\.sellyautomotive\.com"),
        (r"^.*\.sellyautomotive\.com$",),
    ),
    _ChatWidgetRule(
        "sandra_ai",
        ("sandra.ai", "sandra ai", "sandra chat"),
        (r"sandra\.ai", r"cdn\.sandra\.ai", r"app\.sandra\.ai"),
        (r"^.*\.sandra\.ai$",),
    ),
    _ChatWidgetRule(
        "autofi",
        ("autofi.com", "autofi chat", "autofi.io"),
        (r"autofi\.com", r"autofi\.io", r"cdn\.autofi\.com"),
        (r"^.*\.autofi\.com$", r"^.*\.autofi\.io$"),
    ),
    _ChatWidgetRule(
        "activengage",
        ("activengage.com", "activengage chat"),
        (r"activengage\.com",),
        (r"^.*\.activengage\.com$",),
    ),
    _ChatWidgetRule(
        "contact_at_once",
        ("contactatonce.com", "contact at once"),
        (r"contactatonce\.com",),
        (r"^.*\.contactatonce\.com$",),
    ),
    _ChatWidgetRule(
        "carchat24",
        ("carchat24.com", "car chat 24"),
        (r"carchat24\.com",),
        (r"^.*\.carchat24\.com$",),
    ),
    _ChatWidgetRule(
        "livechat",
        ("livechatinc.com", "livechat-widget"),
        (r"livechatinc\.com", r"livechat-widget"),
        (r"^.*\.livechatinc\.com$",),
    ),
    _ChatWidgetRule(
        "intercom",
        ("intercom.io", "intercomcdn.com", "intercom-messenger"),
        (r"intercom(?:cdn)?\.com", r"intercom\.io"),
        (r"^.*\.intercom\.io$", r"^.*\.intercomcdn\.com$"),
    ),
    _ChatWidgetRule(
        "zendesk",
        ("static.zdassets.com", "zendesk web widget", "zopim"),
        (r"zdassets\.com", r"zopim\.com"),
        (r"^.*\.zdassets\.com$", r"^.*\.zopim\.com$"),
    ),
    _ChatWidgetRule(
        "drift",
        ("drift.com", "driftt.com", "drift-widget"),
        (r"driftt?\.com",),
        (r"^.*\.driftt?\.com$",),
    ),
    _ChatWidgetRule(
        "conversica",
        ("conversica.com", "conversica ai"),
        (r"conversica\.com",),
        (r"^.*\.conversica\.com$",),
    ),
    _ChatWidgetRule(
        "autoconverse",
        ("autoconverse.com", "autoconverse chat"),
        (r"autoconverse\.com",),
        (r"^.*\.autoconverse\.com$",),
    ),
    _ChatWidgetRule(
        "carbuddy",
        ("carbuddyai.com", "carbuddy webchat"),
        (r"carbuddyai\.com",),
        (r"^.*\.carbuddyai\.com$",),
    ),
    _ChatWidgetRule(
        "chatbeacon",
        ("chatbeacon.ai", "chatbeacon"),
        (r"chatbeacon\.ai",),
        (r"^.*\.chatbeacon\.ai$",),
    ),
    _ChatWidgetRule(
        "dealerbot",
        ("dealerbot.co.uk", "dealerbot"),
        (r"dealerbot\.co\.uk",),
        (r"^.*\.dealerbot\.co\.uk$",),
    ),
)

_COMPILED: list[tuple[_ChatWidgetRule, list[re.Pattern[str]]]] = []
for rule in _RULES:
    patterns = [re.compile(p, re.I) for p in rule.html_regexes + rule.host_regexes]
    _COMPILED.append((rule, patterns))


# A generic result is intentionally limited to implementation signatures, not
# a dealer merely writing "chat with us" on a contact page.
_GENERIC_WIDGET_PATTERNS = (
    re.compile(r"<(?:iframe|script)\b[^>]+(?:src=)?[^>]*(?:chatbot|chat[-_ ]?widget|livechat|messenger)", re.I),
    re.compile(r"(?:class|id|data-[\w-]+)=[\"'][^\"']*(?:chat[-_ ]?(?:launcher|widget|button)|livechat|chatbot)[^\"']*[\"']", re.I),
)


def _external_hosts(html: str) -> set[str]:
    hosts: set[str] = set()
    for raw in re.findall(
        r'<(?:script|link|img|a|iframe)[^>]+(?:src|href)=["\']([^"\']+)["\']',
        html,
        re.I,
    ):
        if not raw.startswith("http"):
            continue
        host = urlparse(raw).netloc.lower()
        if host:
            hosts.add(host)
    return hosts


def detect_chat_widgets(html: str) -> str:
    """
    Return comma-separated display names of detected chat widgets, or empty string.
    """
    low = html.lower()
    hosts = _external_hosts(html)
    found: list[str] = []

    for rule, compiled in _COMPILED:
        matched = False
        for sub in rule.html_substrings:
            if sub in low:
                matched = True
                break
        if not matched:
            html_patterns = [p for p in compiled if not p.pattern.startswith("^")]
            for pat in html_patterns:
                if pat.search(low):
                    matched = True
                    break
        if not matched:
            host_patterns = [p for p in compiled if p.pattern.startswith("^")]
            for host in hosts:
                for pat in host_patterns:
                    if pat.search(host):
                        matched = True
                        break
                if matched:
                    break
        if matched:
            found.append(_DISPLAY_NAMES.get(rule.provider_id, rule.provider_id))

    order = {name: i for i, name in enumerate(_DISPLAY_NAMES.values())}
    found.sort(key=lambda n: order.get(n, 999))
    if found:
        return ", ".join(found)
    if any(pattern.search(html) for pattern in _GENERIC_WIDGET_PATTERNS):
        return "Generic chat widget"
    return ""
