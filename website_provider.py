"""
Detect third-party website platforms used by auto dealer sites.

Start with CarsForSale (SiteFlex); add more providers to PROVIDERS below.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

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


@dataclass(frozen=True, slots=True)
class ProviderRule:
    """One detectable platform; extend PROVIDERS for DealerOn, Dealer.com, etc."""

    provider_id: str
    display_name: str
    # Substrings in lowercased HTML (strong when unique to the vendor).
    html_substrings: tuple[str, ...] = ()
    # Regexes applied to lowercased HTML.
    html_regexes: tuple[str, ...] = ()
    # Regexes on external hostnames (from script/link/img src).
    host_regexes: tuple[str, ...] = ()
    # Points per hit; provider wins if total score >= min_score.
    points_substring: int = 30
    points_regex: int = 25
    points_host: int = 35
    min_score: int = 25


def _compile_rules(rules: list[ProviderRule]) -> list[tuple[ProviderRule, list[re.Pattern[str]]]]:
    out: list[tuple[ProviderRule, list[re.Pattern[str]]]] = []
    for rule in rules:
        patterns = [re.compile(p, re.I) for p in rule.html_regexes + rule.host_regexes]
        out.append((rule, patterns))
    return out


# Canonical display names (used by enrich_dealers.py).
TARGET_PROVIDER_NAMES: tuple[str, ...] = (
    "DealerSync",
    "Dealr.cloud",
    "CarsForSale",
    "DealerCenter",
    "Dealer Car Search",
    "AutoManager",
    "Frazer DMS",
    "VinSolutions",
    "Tekion",
    "DealerSocket",
    "CDK Global",
    "DealerOn",
    "Dealer Inspire",
)

PROVIDERS: list[ProviderRule] = [
    ProviderRule(
        provider_id="dealersync",
        display_name="DealerSync",
        html_substrings=(
            "dealersync.com",
            "cdn.dealersync.com",
            "powered by dealersync",
        ),
        html_regexes=(
            r"dealersync\.com",
            r"cdn\.dealersync\.com",
            r"dealersync\.net",
        ),
        host_regexes=(r"^.*\.dealersync\.com$", r"^dealersync\.com$"),
    ),
    ProviderRule(
        provider_id="dealr_cloud",
        display_name="Dealr.cloud",
        html_substrings=(
            "dealr.cloud",
            "powered by dealr",
            "dealrcloud",
        ),
        html_regexes=(
            r"dealr\.cloud",
            r"cdn\.dealr\.cloud",
            r"app\.dealr\.cloud",
        ),
        host_regexes=(r"^.*\.dealr\.cloud$",),
    ),
    ProviderRule(
        provider_id="dealercenter",
        display_name="DealerCenter",
        html_substrings=(
            "lib.dealercenterwsstatic.net",
            "imagescf.dealercenter.net",
            "dcdws.blob.core.windows.net",
            "dwssecuredforms.dealercenter.net",
            "/dealercenter/img/",
            "dealercenter.website",
            "dws-website-by",
        ),
        html_regexes=(
            r"lib\.dealercenterwsstatic\.net",
            r"imagescf\.dealercenter\.net",
            r"dcdws\.blob\.core\.windows\.net/dws-\d+",
            r"dwssecuredforms\.dealercenter\.net",
            r"chat-cf\.dealercenter\.net",
            r"/dealercenter/(?:img|fonts|lib)/",
            r"var\s+dws_const_",
            r"id=['\"]dws_[^'\"]+['\"]",
            r"#dwsmainwrapper",
            r"data-handle=['\"]dws_",
        ),
        host_regexes=(
            r"^lib\.dealercenterwsstatic\.net$",
            r"^imagescf\.dealercenter\.net$",
            r"^chat-cf\.dealercenter\.net$",
            r"^dwssecuredforms\.dealercenter\.net$",
        ),
        points_substring=35,
        points_regex=28,
        points_host=40,
        min_score=25,
    ),
    ProviderRule(
        provider_id="carsforsale",
        display_name="CarsForSale",
        html_substrings=(
            "powered by carsforsale.com",
            "powered by carsforsale",
            "siteflex",
        ),
        html_regexes=(
            r"cdn\d{2}\.carsforsale\.com",
            r"signin\.carsforsale\.com",
            r"carsforsale\.com/wwwroot/bundles/",
            r"carsforsale\.com/dealerlogos/",
            r"dns-prefetch[^>]+cdn\d{2}\.carsforsale\.com",
        ),
        host_regexes=(
            r"^cdn\d{2}\.carsforsale\.com$",
            r"^signin\.carsforsale\.com$",
            r"^images\.carsforsale\.com$",
        ),
        points_substring=40,
        points_regex=30,
        points_host=40,
        min_score=25,
    ),
    ProviderRule(
        provider_id="dealer_car_search",
        display_name="Dealer Car Search",
        html_substrings=(
            "dealercarsearch.com",
            "dealer car search",
            "dcsinventory",
        ),
        html_regexes=(
            r"dealercarsearch\.com",
            r"cdn\.dealercarsearch\.com",
            r"dcsinventory",
        ),
        host_regexes=(r"^.*\.dealercarsearch\.com$",),
    ),
    ProviderRule(
        provider_id="automanager",
        display_name="AutoManager",
        html_substrings=(
            "automanager.com",
            "powered by automanager",
            "zoocar.com",
            "deskmanager",
        ),
        html_regexes=(
            r"automanager\.com",
            r"cdn\.automanager\.com",
            r"zoocar\.com",
            r"deskmanageronline",
        ),
        host_regexes=(r"^.*\.automanager\.com$", r"^.*\.zoocar\.com$"),
    ),
    ProviderRule(
        provider_id="frazer",
        display_name="Frazer DMS",
        html_substrings=(
            "frazer.com",
            "frazer computing",
            "frazerdms",
        ),
        html_regexes=(
            r"frazer\.com",
            r"frazercomputing\.com",
            r"frazerdms",
        ),
        host_regexes=(r"^.*\.frazer\.com$",),
    ),
    ProviderRule(
        provider_id="vinsolutions",
        display_name="VinSolutions",
        html_substrings=(
            "vinsolutions.com",
            "vin solutions",
            "contactatonce",
            "leadbox",
            "caochathub",
        ),
        html_regexes=(
            r"vinsolutions\.com",
            r"vinconnect\.com",
            r"contactatonce\.com",
            r"leadbox\.com",
            r"caochathub",
        ),
        host_regexes=(
            r"^.*\.vinsolutions\.com$",
            r"^.*\.contactatonce\.com$",
            r"^.*\.leadbox\.com$",
        ),
    ),
    ProviderRule(
        provider_id="tekion",
        display_name="Tekion",
        html_substrings=(
            "tekion.com",
            "tekioncloud",
            "tekion api",
        ),
        html_regexes=(
            r"tekion\.com",
            r"tekioncloud\.com",
            r"cdn\.tekion\.io",
            r"api\.tekion\.io",
        ),
        host_regexes=(r"^.*\.tekion\.com$", r"^.*\.tekioncloud\.com$", r"^.*\.tekion\.io$"),
    ),
    ProviderRule(
        provider_id="dealersocket",
        display_name="DealerSocket",
        html_substrings=(
            "dealersocket.com",
            "dealer socket",
            "dsnextgen",
            "inventoryplus",
        ),
        html_regexes=(
            r"dealersocket\.com",
            r"dsnextgen\.com",
            r"inventoryplus\.dealersocket",
            r"cdn\.dealersocket\.com",
        ),
        host_regexes=(r"^.*\.dealersocket\.com$", r"^.*\.dsnextgen\.com$"),
    ),
    ProviderRule(
        provider_id="cdk",
        display_name="CDK Global",
        html_substrings=(
            "cdkglobal.com",
            "cdk.com",
            "digital dealers",
            "elead",
            "fortellis",
        ),
        html_regexes=(
            r"cdkglobal\.com",
            r"cdk\.com/(?:assets|scripts)",
            r"eleadcrm\.com",
            r"fortellis\.io",
            r"digitaldealers",
        ),
        host_regexes=(
            r"^.*\.cdkglobal\.com$",
            r"^.*\.eleadcrm\.com$",
            r"^.*\.fortellis\.io$",
        ),
    ),
    ProviderRule(
        provider_id="dealeron",
        display_name="DealerOn",
        html_substrings=(
            "dealeron.com",
            "static.dealeron.com",
            "powered by dealeron",
        ),
        html_regexes=(
            r"dealeron\.com",
            r"static\.dealeron\.com",
            r"assets\.dealeron\.com",
            r"cdn\.dealeron\.com",
        ),
        host_regexes=(r"^.*\.dealeron\.com$",),
    ),
    ProviderRule(
        provider_id="dealer_inspire",
        display_name="Dealer Inspire",
        html_substrings=(
            "dealerinspire.com",
            "dealer inspire",
            "di-uploads",
            "cdn.dealerinspire",
        ),
        html_regexes=(
            r"dealerinspire\.com",
            r"cdn\.dealerinspire\.com",
            r"di-uploads",
            r"dealerinspire\.net",
        ),
        host_regexes=(r"^.*\.dealerinspire\.com$", r"^.*\.dealerinspire\.net$"),
    ),
]

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
