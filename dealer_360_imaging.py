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
    resource_patterns: tuple[str, ...] = ()


# These are delivery/widget signatures, not simply mentions of a vendor in
# visible text.  Add a rule only after confirming the signature on a dealer
# page, which keeps competitor reporting useful rather than noisy.
_RULES: tuple[_ViewerRule, ...] = (
    # Impel also delivers Chat AI and other products from impel.io. A bare
    # impel.io host is therefore not evidence of a vehicle spin viewer.
    _ViewerRule(
        "Impel / SpinCar",
        ("spincar.com", "spincar-viewer", "impel.io/360", "impel.io/spin"),
        (r"(?:^|\.)spincar\.com$",),
    ),
    # CarCutter also supplies ordinary dealer photos.  Its 360 product uses
    # the dedicated WebPlayer bundle, not merely an image on its CDN.
    _ViewerRule(
        "CarCutter",
        ("carcutter-360", "car-cutter-360-js-module", "car-cutter.com/libs/web-player"),
        (),
        (r"(?:cdn\.)?car-cutter\.com/libs/web-player/",),
    ),
    _ViewerRule("AutoPlay Media", ("autoplaymedia.com", "autoplay 360"),
                (r"(?:^|\.)autoplaymedia\.com$",)),
    _ViewerRule("Car360", ("car360.com", "car360viewer", "car-360-viewer"),
                (r"(?:^|\.)car360\.com$",)),
    # Dealer Image Pro can also serve ordinary vehicle photos.  Only report
    # it when the embedded resource itself identifies a spin/viewer endpoint.
    _ViewerRule(
        "Dealer Image Pro",
        ("dealer image pro 360",),
        (),
        (r"dealerimagepro\.com/[^?#]*(?:360|spin|turntable|viewer)",),
    ),
    _ViewerRule("360CarPics", ("360carpics.com", "360 car pics"),
                (r"(?:^|\.)360carpics\.com$",)),
    # Verified on DealerConnect360: the provider's spin player is loaded with
    # a vehicle-specific data-spin identifier.
    _ViewerRule(
        "InstaVid 360",
        ("spin360.lite.js",),
        (),
        (r"static\.instavid360\.com/p/[^?#]*/spin360(?:\.lite)?\.js",),
    ),
)

_GENERIC_VIEWER_PATTERNS = (
    re.compile(r"<(?:iframe|model-viewer)\b[^>]*(?:360(?:viewer|view|spin)|spin(?:car|view|viewer)|vehicle[-_ ]?turntable)", re.I),
    re.compile(r"(?:data-|class=|id=)[\"'][^\"']*(?:360[-_ ]?(?:viewer|view|spin)|spin[-_ ]?(?:car|viewer)|turntable)[^\"']*[\"']", re.I),
    re.compile(r"<(?:canvas|script)\b[^>]*(?:360[-_ ]?(?:viewer|spin)|spin[-_ ]?(?:viewer|car)|turntable)", re.I),
)


def _resource_urls(html: str) -> set[str]:
    urls: set[str] = set()
    for raw in re.findall(r"<(?:script|iframe|img|link)[^>]+(?:src|href)=[\"']([^\"']+)", html, re.I):
        if raw.startswith(("http://", "https://", "//")):
            urls.add("https:" + raw if raw.startswith("//") else raw)
    return urls


def _hosts(urls: set[str]) -> set[str]:
    hosts: set[str] = set()
    for url in urls:
        host = urlparse(url).netloc.lower()
        if host:
            hosts.add(host.split(":", 1)[0])
    return hosts


def detect_360_viewers(html: str) -> str:
    """Return vendor names, or ``Generic 360° viewer`` when only the widget is known."""
    if not html:
        return ""
    low = html.lower()
    resource_urls = _resource_urls(html)
    hosts = _hosts(resource_urls)
    found: list[str] = []
    for rule in _RULES:
        if any(marker in low for marker in rule.markers):
            found.append(rule.name)
            continue
        if any(re.search(pattern, host, re.I) for host in hosts for pattern in rule.host_patterns):
            found.append(rule.name)
            continue
        if any(re.search(pattern, url, re.I) for url in resource_urls for pattern in rule.resource_patterns):
            found.append(rule.name)
    if found:
        return ", ".join(found)
    if any(pattern.search(html) for pattern in _GENERIC_VIEWER_PATTERNS):
        return "Generic 360° viewer"
    return ""
