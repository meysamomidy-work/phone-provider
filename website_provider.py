"""
Detect third-party website platforms used by auto dealer sites.

Detection signatures live in provider_rules.py (one ProviderRule per platform).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from dealer_platforms import DEALER_PLATFORMS
from provider_rules import PROVIDERS, ProviderRule

log = logging.getLogger("website_provider")

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# DealerCenter sites often serve "/" or "/inventory"; CarsForSale often uses "/cars-for-sale".
FALLBACK_PATHS = (
    "/inventory",
    "",
    "/",
    "/home",
    "/cars-for-sale",
    "/vehicles",
    "/used-cars",
    "/search",
)

_CLOUDFLARE_MARKERS = ("just a moment", "cf_chl_opt", "challenges.cloudflare.com")

MIN_HTML_BYTES = 2_500


@dataclass(frozen=True, slots=True)
class ProviderMatch:
    provider_id: str
    display_name: str
    score: int
    signals: tuple[str, ...]


def _compile_rules(rules: list[ProviderRule]) -> list[tuple[ProviderRule, list[re.Pattern[str]]]]:
    out: list[tuple[ProviderRule, list[re.Pattern[str]]]] = []
    for rule in rules:
        patterns = [re.compile(p, re.I) for p in rule.html_regexes + rule.host_regexes]
        out.append((rule, patterns))
    return out


# Canonical display names (used by enrich_dealers.py).
TARGET_PROVIDER_NAMES: tuple[str, ...] = DEALER_PLATFORMS

_COMPILED = _compile_rules(PROVIDERS)


def _is_cloudflare_challenge(html: str) -> bool:
    low = html.lower()
    return any(m in low for m in _CLOUDFLARE_MARKERS)


def normalize_dealer_url(url: str) -> str | None:
    url = (url or "").strip()
    if not url or url.lower() in ("not specified", "n/a", "none", "-"):
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}".rstrip("/") + "/"


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


def _fetch_one(url: str, timeout: float) -> tuple[int, str, str]:
    try:
        from curl_cffi import requests as http

        r = http.get(
            url,
            impersonate="chrome131",
            timeout=timeout,
            allow_redirects=True,
            headers=DEFAULT_HEADERS,
        )
        return r.status_code, r.url, r.text or ""
    except ImportError:
        import requests as http

        r = http.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        return r.status_code, r.url, r.text or ""


def fetch_dealer_html(
    base_url: str,
    *,
    timeout: float = 30.0,
    paths: tuple[str, ...] = FALLBACK_PATHS,
) -> tuple[str, str] | None:
    """
    Return (final_url, html) for the first path that returns a usable document.
    """
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    cloudflare_blocked = False

    for path in paths:
        url = origin if path in ("", "/") else urljoin(origin + "/", path.lstrip("/"))
        try:
            status, final_url, html = _fetch_one(url, timeout)
        except Exception as exc:
            log.warning("fetch failed %s: %s", url, exc)
            continue
        if status == 200 and len(html) >= MIN_HTML_BYTES:
            log.debug("fetched %s (%s bytes)", final_url, len(html))
            return final_url, html
        if _is_cloudflare_challenge(html):
            cloudflare_blocked = True
        log.debug("skip %s status=%s bytes=%s", url, status, len(html))

    if cloudflare_blocked:
        log.warning(
            "site behind Cloudflare challenge (try from a residential IP or browser); %s",
            base_url,
        )
    return None


def score_provider(html: str, hosts: set[str]) -> list[ProviderMatch]:
    low = html.lower()
    matches: list[ProviderMatch] = []

    for rule, compiled in _COMPILED:
        score = 0
        signals: list[str] = []

        for sub in rule.html_substrings:
            if sub in low:
                score += rule.points_substring
                signals.append(f"html:{sub!r}")

        host_patterns = [p for p in compiled if p.pattern.startswith("^")]
        html_patterns = [p for p in compiled if not p.pattern.startswith("^")]

        for pat in html_patterns:
            if pat.search(low):
                score += rule.points_regex
                signals.append(f"regex:{pat.pattern}")

        for host in sorted(hosts):
            for pat in host_patterns:
                if pat.search(host):
                    score += rule.points_host
                    signals.append(f"host:{host}")
                    break

        if score >= rule.min_score:
            matches.append(
                ProviderMatch(
                    provider_id=rule.provider_id,
                    display_name=rule.display_name,
                    score=score,
                    signals=tuple(signals),
                )
            )

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def detect_from_html(html: str, *, source_url: str = "") -> ProviderMatch | None:
    """Score providers from HTML already fetched (e.g. saved from a browser)."""
    hosts = _external_hosts(html)
    if source_url:
        own = urlparse(source_url).netloc.lower()
        if own:
            hosts.discard(own)
    ranked = score_provider(html, hosts)
    return ranked[0] if ranked else None


def detect_website_provider(
    website_url: str,
    *,
    timeout: float = 30.0,
    html: str | None = None,
) -> ProviderMatch | None:
    """
    Detect the platform behind a dealer website URL.

    Returns the best ProviderMatch or None if unknown / unreachable.
    """
    if html:
        match = detect_from_html(html, source_url=website_url)
        if match:
            log.info("provider=%s score=%s (from supplied HTML)", match.provider_id, match.score)
        return match

    base = normalize_dealer_url(website_url)
    if not base:
        return None

    fetched = fetch_dealer_html(base, timeout=timeout)
    if not fetched:
        log.warning("no usable HTML for %s", website_url)
        return None

    final_url, html = fetched
    hosts = _external_hosts(html)
    own = urlparse(final_url).netloc.lower()
    hosts.discard(own)

    ranked = score_provider(html, hosts)
    if not ranked:
        return None
    best = ranked[0]
    log.info(
        "provider=%s score=%s url=%s signals=%s",
        best.provider_id,
        best.score,
        final_url,
        best.signals[:6],
    )
    return best
