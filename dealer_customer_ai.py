"""High-confidence detection of customer-facing AI on dealer websites.

This intentionally does not mark every chat widget as AI.  A result means a
known automotive AI assistant was embedded, or the page explicitly describes
its customer conversation widget as AI-powered.
"""
from __future__ import annotations

import re


_VENDOR_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hammer", ("hammer.ai", "hammercorp", "usehammer")),
    ("DealerAI", ("dealerai.com", "dealer ai chat")),
    ("Drivee.ai", ("drivee.ai", "salesagent-widget.web.app", "salesagentwidget")),
    ("Matador", ("matador.ai", "matador automotive")),
    ("Toma", ("toma.com", "toma automotive")),
    ("Numa", ("numa.com", "numa ai")),
    ("Rybo", ("rybo.ai",)),
    ("Sandra AI", ("sandra.ai", "sandra ai")),
    ("Conversica", ("conversica.com", "conversica ai")),
    ("AutoConverse", ("autoconverse.com", "autoconverse chat")),
    ("CarBuddy", ("carbuddyai.com", "carbuddy webchat")),
    ("ChatBeacon", ("chatbeacon.ai", "chatbeacon")),
    ("Dealerbot", ("dealerbot.co.uk", "dealerbot")),
)

# Apollo AssistantAI is native to Team Velocity's website platform, rather
# than a conventional third-party iframe.  A Team Velocity site alone is not
# enough to establish that the optional AI assistant is enabled, so these
# markers are only used with direct assistant evidence below.
_TEAM_VELOCITY_MARKERS = (
    "teamvelocitymarketing.com",
    "teamvelocity.com",
    "apollo assistantai",
    "apolloassistantai",
    "assistantai",
)

# Require an AI claim together with an actual conversational-control signal.
# This prevents a dealer's blog post or a marketing script from becoming a
# false positive.
_EXPLICIT_AI = re.compile(
    r"(?:ai[- ]?(?:powered )?(?:chat|assistant|agent|concierge|conversation)|"
    r"(?:chat|assistant|agent|concierge)[^<]{0,80}?(?:powered by )?ai|"
    r"(?:virtual salesperson|digital assistant)[^<]{0,80}?(?:ai|artificial intelligence))",
    re.I,
)
_CONVERSATION_CONTROL = re.compile(
    r"(?:chat[-_ ]?widget|chatbot|open[-_ ]?chat|livechat|messag(?:e|ing)|"
    r"conversation[-_ ]?widget|virtual[-_ ]?assistant)",
    re.I,
)


def detect_customer_ai(
    html: str,
    *,
    source_url: str = "",
    website_provider: str = "",
) -> str:
    """Return customer-facing AI provider(s), using known site-platform context.

    ``website_provider`` must be the provider detected from the dealer page,
    not a guess from the dealer's own business name.  This lets a native
    assistant be attributed without marking every site on that platform as AI.
    """
    if not html:
        return ""
    low = html.lower()
    platform_context = f"{source_url} {website_provider}".lower()
    has_team_velocity = (
        "team velocity" in platform_context
        or any(marker in low for marker in _TEAM_VELOCITY_MARKERS[:2])
    )
    has_apollo_assistant = any(marker in low for marker in _TEAM_VELOCITY_MARKERS[2:])

    if has_apollo_assistant:
        return "Team Velocity Apollo AssistantAI"

    found = [name for name, markers in _VENDOR_MARKERS if any(marker in low for marker in markers)]
    if found:
        return ", ".join(found)
    if _EXPLICIT_AI.search(html) and _CONVERSATION_CONTROL.search(html):
        if has_team_velocity:
            return "Team Velocity Apollo AssistantAI"
        return "AI customer assistant (vendor unknown)"
    return ""
