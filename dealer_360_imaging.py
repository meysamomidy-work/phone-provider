"""Detect interactive, spin-style vehicle imaging embedded in dealer pages.

The detector reports the vendor when its delivery domain is present.  It also
reports a conservative generic result for a real 360 viewer whose vendor is
not in the rule set.  It does not treat ordinary photo galleries as 360
imaging.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class _ViewerRule:
    name: str
    markers: tuple[str, ...]
    host_patterns: tuple[str, ...]


# These are delivery/widget signatures, not simply mentions of a vendor in
# visible text.  Add a rule only after confirming the signature on a dealer
# page, which keeps competitor reporting useful rather than noisy.
_RULES: tuple[_ViewerRule, ...] = (
    _ViewerRule("Impel / SpinCar", ("spincar.com", "impel.io/360", "spincar-viewer"),
                (r"(?:^|\.)spincar\.com$", r"(?:^|\.)impel\.io$")),
    _ViewerRule("CarCutter", ("carcutter.com", "carcutter-360"),
                (r"(?:^|\.)carcutter\.com$",)),
    _ViewerRule("AutoPlay Media", ("autoplaymedia.com", "autoplay 360"),
                (r"(?:^|\.)autoplaymedia\.com$",)),
    _ViewerRule("Car360", ("car360.com", "car360viewer", "car-360-viewer"),
                (r"(?:^|\.)car360\.com$",)),
    _ViewerRule("Dealer Image Pro", ("dealerimagepro.com", "dealer image pro 360"),
                (r"(?:^|\.)dealerimagepro\.com$",)),
    _ViewerRule("360CarPics", ("360carpics.com", "360 car pics"),
                (r"(?:^|\.)360carpics\.com$",)),
)

_GENERIC_VIEWER_PATTERNS = (
    re.compile(r"<(?:iframe|model-viewer)\b[^>]*(?:360(?:viewer|view|spin)|spin(?:car|view|viewer)|vehicle[-_ ]?turntable)", re.I),
    re.compile(r"(?:data-|class=|id=)[\"'][^\"']*(?:360[-_ ]?(?:viewer|view|spin)|spin[-_ ]?(?:car|viewer)|turntable)[^\"']*[\"']", re.I),
    re.compile(r"<(?:canvas|script)\b[^>]*(?:360[-_ ]?(?:viewer|spin)|spin[-_ ]?(?:viewer|car)|turntable)", re.I),
)


def _hosts(html: str) -> set[str]:
    hosts: set[str] = set()
    for raw in re.findall(r"<(?:script|iframe|img|link)[^>]+(?:src|href)=[\"']([^\"']+)", html, re.I):
        if raw.startswith(("http://", "https://", "//")):
            host = urlparse("https:" + raw if raw.startswith("//") else raw).netloc.lower()
            if host:
                hosts.add(host.split(":", 1)[0])
    return hosts


def detect_360_viewers(html: str) -> str:
    """Return vendor names, or ``Generic 360° viewer`` when only the widget is known."""
    if not html:
        return ""
    low = html.lower()
    hosts = _hosts(html)
    found: list[str] = []
    for rule in _RULES:
        if any(marker in low for marker in rule.markers):
            found.append(rule.name)
            continue
        if any(re.search(pattern, host, re.I) for host in hosts for pattern in rule.host_patterns):
            found.append(rule.name)
    if found:
        return ", ".join(found)
    if any(pattern.search(html) for pattern in _GENERIC_VIEWER_PATTERNS):
        return "Generic 360° viewer"
    return ""
