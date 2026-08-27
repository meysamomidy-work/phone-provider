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


def detect_customer_ai(html: str) -> str:
    """Return comma-separated AI providers or an explicit generic AI result."""
    if not html:
        return ""
    low = html.lower()
    found = [name for name, markers in _VENDOR_MARKERS if any(marker in low for marker in markers)]
    if found:
        return ", ".join(found)
    if _EXPLICIT_AI.search(html) and _CONVERSATION_CONTROL.search(html):
        return "AI customer assistant (vendor unknown)"
    return ""
