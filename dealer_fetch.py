"""
Fetch dealer website HTML with HTTP impersonation and optional real-browser fallback.

Use fetch_mode='auto' (default): fast curl_cffi first, Playwright if a challenge is detected.
"""
from __future__ import annotations

import logging
import random
import re
import time
from enum import Enum
from urllib.parse import urljoin, urlparse

log = logging.getLogger("dealer_fetch")

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_NAV_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

FALLBACK_PATHS = (
    # "/inventory",
    "",
    # "/",
    # "/home",
    # "/cars-for-sale",
    # "/vehicles",
    # "/used-cars",
    # "/search",
)

_CHALLENGE_MARKERS = (
    "just a moment",
    "cf_chl_opt",
    "challenges.cloudflare.com",
    "cf-turnstile",
    "turnstile.render",
    "hcaptcha.com",
    "google.com/recaptcha",
    "g-recaptcha",
    "verify you are human",
    "verify that you are human",
    "checking your browser",
    "enable javascript and cookies",
    "attention required",
    "access denied",
    "ray id",
    "cf-browser-verification",
    "bot detection",
    "blocked",
    "captcha",
)

MIN_HTML_BYTES = 2_500

# curl_cffi browser profiles to rotate on retries
_CURL_IMPERSONATE = ("chrome131", "chrome124", "chrome120", "edge131")


class FetchMode(str, Enum):
    AUTO = "auto"
    HTTP = "http"
    BROWSER = "browser"


def is_challenge_page(html: str) -> bool:
    if not html or len(html) < 200:
        return True
    low = html.lower()
    return any(m in low for m in _CHALLENGE_MARKERS)


def is_usable_html(html: str, *, status: int = 200) -> bool:
    return status == 200 and len(html) >= MIN_HTML_BYTES and not is_challenge_page(html)


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


def _origin_paths(base_url: str, paths: tuple[str, ...]) -> list[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    urls: list[str] = []
    seen: set[str] = set()
    for path in paths:
        u = origin if path in ("", "/") else urljoin(origin + "/", path.lstrip("/"))
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def _jitter(seconds: float = 0.4) -> None:
    time.sleep(random.uniform(0.15, seconds))


def _fetch_http_one(
    url: str,
    timeout: float,
    *,
    session: object | None,
    referer: str | None,
    impersonate: str,
) -> tuple[int, str, str, str]:
    """Return (status, final_url, html, method_label)."""
    headers = dict(_NAV_HEADERS)
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = (
            "same-origin"
            if urlparse(referer).netloc == urlparse(url).netloc
            else "cross-site"
        )

    try:
        from curl_cffi import requests as http

        client = session if session is not None else http.Session(impersonate=impersonate)
        r = client.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers=headers,
        )
        return r.status_code, r.url, r.text or "", f"curl_cffi/{impersonate}"
    except ImportError:
        import requests as http

        r = http.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        return r.status_code, r.url, r.text or "", "requests"


def fetch_http(
    base_url: str,
    *,
    timeout: float = 30.0,
    paths: tuple[str, ...] = FALLBACK_PATHS,
) -> tuple[str, str, str] | None:
    """
    Session-based HTTP fetch with profile rotation and referer chaining.
    Returns (final_url, html, method_label) or None.
    """
    urls = _origin_paths(base_url, paths)
    last_referer: str | None = None
    challenge_seen = False

    for impersonate in _CURL_IMPERSONATE:
        try:
            from curl_cffi import requests as http

            session = http.Session(impersonate=impersonate)
        except ImportError:
            session = None

        for url in urls:
            try:
                status, final_url, html, label = _fetch_http_one(
                    url,
                    timeout,
                    session=session,
                    referer=last_referer,
                    impersonate=impersonate,
                )
            except Exception as exc:
                log.debug("http fetch failed %s (%s): %s", url, impersonate, exc)
                continue

            if is_challenge_page(html):
                challenge_seen = True
                log.debug("challenge page %s (%s bytes)", url, len(html))
                continue

            if is_usable_html(html, status=status):
                log.debug("http ok %s via %s (%s bytes)", final_url, label, len(html))
                return final_url, html, label

            log.debug("http skip %s status=%s bytes=%s", url, status, len(html))
            last_referer = final_url
            _jitter(0.35)

        _jitter(0.6)

    if challenge_seen:
        log.info("HTTP blocked by challenge/CAPTCHA for %s", base_url)
    return None


def fetch_browser(
    url: str,
    *,
    timeout: float = 30.0,
    headed: bool = False,
    wait_after_load_ms: int = 4_000,
) -> tuple[str, str, str] | None:
    """
    Load URL in Chromium via Playwright (harder to fingerprint than plain HTTP).
    Returns (final_url, html, method_label) or None.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        log.warning("playwright not installed (%s). Run: pip install playwright && playwright install chromium", exc)
        return None

    timeout_ms = int(timeout * 1000)
    label = "playwright/headed" if headed else "playwright/headless"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=CHROME_UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Allow Cloudflare / Turnstile JS challenges time to complete.
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15_000))
            except Exception:
                pass
            page.wait_for_timeout(wait_after_load_ms)

            html = page.content()
            final_url = page.url

            if is_usable_html(html):
                log.debug("browser ok %s (%s bytes)", final_url, len(html))
                return final_url, html, label

            if is_challenge_page(html):
                log.info("browser still on challenge page for %s", url)
            else:
                log.info("browser page too small or non-200 content for %s (%s bytes)", url, len(html))
            return None
        except Exception as exc:
            log.warning("browser fetch failed %s: %s", url, exc)
            return None
        finally:
            context.close()
            browser.close()


def extract_resource_urls(html: str, base_url: str) -> set[str]:
    """Return absolute script/frame/style/image URLs referenced by an HTML page."""
    urls: set[str] = set()
    for raw in re.findall(
        r'<(?:script|link|img|iframe|source)[^>]+(?:src|href)=["\']([^"\']+)',
        html or "",
        re.I,
    ):
        raw = raw.strip()
        if raw and not raw.startswith(("data:", "javascript:", "mailto:")):
            urls.add(urljoin(base_url, raw))
    return urls


def fetch_browser_with_resources(
    url: str,
    *,
    timeout: float = 30.0,
    headed: bool = False,
    wait_after_load_ms: int = 4_000,
) -> tuple[str, str, str, set[str]] | None:
    """Load a page in Chromium and capture useful browser-loaded resource URLs.

    The response listener sees integrations injected after the initial HTML,
    which is important for chat and vehicle-imaging widgets.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        log.warning("playwright not installed (%s). Run: pip install playwright && playwright install chromium", exc)
        return None

    timeout_ms = int(timeout * 1000)
    label = "playwright/headed+resources" if headed else "playwright/headless+resources"
    resource_urls: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=CHROME_UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )
        page = context.new_page()

        def capture(response: object) -> None:
            try:
                request = response.request  # type: ignore[attr-defined]
                if request.resource_type in {"document", "script", "stylesheet", "iframe", "xhr", "fetch"}:
                    resource_urls.add(response.url)  # type: ignore[attr-defined]
            except Exception:
                # A resource event must never make the dealer page fetch fail.
                pass

        page.on("response", capture)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15_000))
            except Exception:
                pass
            page.wait_for_timeout(wait_after_load_ms)
            html = page.content()
            final_url = page.url
            if is_usable_html(html):
                resource_urls.update(extract_resource_urls(html, final_url))
                log.debug("browser resources ok %s (%s resources)", final_url, len(resource_urls))
                return final_url, html, label, resource_urls
            return None
        except Exception as exc:
            log.warning("browser resource fetch failed %s: %s", url, exc)
            return None
        finally:
            context.close()
            browser.close()


def fetch_browser_paths(
    base_url: str,
    *,
    timeout: float = 30.0,
    paths: tuple[str, ...] = FALLBACK_PATHS,
    headed: bool = False,
) -> tuple[str, str, str] | None:
    """Try browser fetch on each path until one returns usable HTML."""
    for url in _origin_paths(base_url, paths):
        result = fetch_browser(url, timeout=timeout, headed=headed)
        if result:
            return result
        _jitter(0.5)
    return None


def fetch_dealer_html(
    base_url: str,
    *,
    timeout: float = 30.0,
    paths: tuple[str, ...] = FALLBACK_PATHS,
    mode: str | FetchMode = FetchMode.AUTO,
    headed: bool = False,
) -> tuple[str, str] | None:
    """
    Return (final_url, html) using the requested fetch mode.

    mode:
      - auto: HTTP first, then browser if blocked
      - http: curl_cffi / requests only
      - browser: Playwright only
    """
    fetch_mode = FetchMode(mode) if isinstance(mode, str) else mode

    if fetch_mode in (FetchMode.AUTO, FetchMode.HTTP):
        http_result = fetch_http(base_url, timeout=timeout, paths=paths)
        if http_result:
            final_url, html, _ = http_result
            return final_url, html
        if fetch_mode == FetchMode.HTTP:
            return None

    browser_result = fetch_browser_paths(
        base_url,
        timeout=timeout,
        paths=paths,
        headed=headed,
    )
    if browser_result:
        final_url, html, _ = browser_result
        return final_url, html
    return None


def fetch_dealer_html_with_resources(
    base_url: str,
    *,
    timeout: float = 30.0,
    paths: tuple[str, ...] = FALLBACK_PATHS,
    mode: str | FetchMode = FetchMode.AUTO,
    headed: bool = False,
    force_browser: bool = False,
) -> tuple[str, str, set[str]] | None:
    """Like :func:`fetch_dealer_html`, plus static/dynamic integration URLs.

    ``force_browser`` is used by the optional deep detector.  It deliberately
    does not change the normal fast HTTP-first enrichment path.
    """
    fetch_mode = FetchMode(mode) if isinstance(mode, str) else mode
    if force_browser and fetch_mode != FetchMode.HTTP:
        for url in _origin_paths(base_url, paths):
            browser_result = fetch_browser_with_resources(url, timeout=timeout, headed=headed)
            if browser_result:
                final_url, html, _, resources = browser_result
                return final_url, html, resources
            _jitter(0.5)

    fetched = fetch_dealer_html(
        base_url,
        timeout=timeout,
        paths=paths,
        mode=fetch_mode,
        headed=headed,
    )
    if not fetched:
        return None
    final_url, html = fetched
    return final_url, html, extract_resource_urls(html, final_url)


def fetch_dealer_html_with_meta(
    base_url: str,
    **kwargs: object,
) -> dict[str, object]:
    """Like fetch_dealer_html but returns diagnostics for test scripts."""
    fetch_mode = FetchMode(kwargs.pop("mode", FetchMode.AUTO))
    timeout = float(kwargs.pop("timeout", 30.0))
    paths = kwargs.pop("paths", FALLBACK_PATHS)
    headed = bool(kwargs.pop("headed", False))

    out: dict[str, object] = {
        "base_url": base_url,
        "mode": fetch_mode.value,
        "success": False,
        "final_url": "",
        "html_bytes": 0,
        "method": "",
        "challenge": False,
        "title": "",
        "error": "",
    }

    if fetch_mode in (FetchMode.AUTO, FetchMode.HTTP):
        http_result = fetch_http(base_url, timeout=timeout, paths=paths)  # type: ignore[arg-type]
        if http_result:
            final_url, html, method = http_result
            out.update(
                success=True,
                final_url=final_url,
                html_bytes=len(html),
                method=method,
                challenge=is_challenge_page(html),
                title=_extract_title(html),
            )
            return out
        if fetch_mode == FetchMode.HTTP:
            out["error"] = "HTTP fetch failed or challenge detected"
            return out

    browser_result = fetch_browser_paths(
        base_url,
        timeout=timeout,
        paths=paths,  # type: ignore[arg-type]
        headed=headed,
    )
    if browser_result:
        final_url, html, method = browser_result
        out.update(
            success=True,
            final_url=final_url,
            html_bytes=len(html),
            method=method,
            challenge=is_challenge_page(html),
            title=_extract_title(html),
        )
        return out

    out["error"] = "Browser fetch failed or challenge still present"
    return out


def _extract_title(html: str) -> str:
    import re

    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I | re.S)
    return (m.group(1).strip() if m else "")[:120]
