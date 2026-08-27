#!/usr/bin/env python3
"""Find official dealer sites missing from CarGurus and Google Maps.

This uses Google Places API (New) and can fall back to Exa, Tavily, or the
independent Brave Search API. It can also use Google Custom Search for existing
API customers. It only accepts a candidate when the returned place/result
agrees with the dealer's name and location/phone, and keeps original source
columns intact.

Example:
  python discover_websites.py enriched_new -o discovered --google-places-api-key YOUR_KEY
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
from tqdm import tqdm

from dealer_fetch import fetch_dealer_html

try:
    from exa_py import Exa
except ImportError:  # Keep Places/Tavily/Brave usable if Exa is not configured.
    Exa = None  # type: ignore[assignment,misc]

try:
    from tavily import TavilyClient
except ImportError:  # Keep Places/Exa/Brave usable if Tavily is not configured.
    TavilyClient = None  # type: ignore[assignment,misc]

log = logging.getLogger("discover_websites")

PLACE_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.websiteUri,"
    "places.nationalPhoneNumber"
)
EMPTY_VALUES = frozenset({"", "not specified", "n/a", "na", "none", "null", "nan", "-"})
DIRECTORY_HOSTS = frozenset({
    "google.com", "facebook.com", "instagram.com", "yelp.com", "cargurus.com",
    "cars.com", "autotrader.com", "carfax.com", "bbb.org", "mapquest.com",
    "yellowpages.com", "dealerrater.com", "kbb.com", "edmunds.com",
    # Social profiles are not the dealership's own website.
    "linkedin.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
    "pinterest.com", "threads.net", "snapchat.com", "whatsapp.com",
    # Search-provider result/profile pages are evidence, never a dealer's own
    # website. Without these exclusions an Exa library page can contain the
    # dealer's name and accidentally pass the on-page matching checks.
    "exa.ai", "tavily.com", "brave.com",
})
CAPTCHA_MARKERS = (
    "captcha", "cf-turnstile", "challenges.cloudflare.com", "just a moment",
    "verify you are human", "checking your browser", "g-recaptcha", "hcaptcha",
)
CAPTCHA_URL_MIN_CONFIDENCE = 90

RESOLVED_WEBSITE_COL = "Resolved Website"
RESOLVED_SOURCE_COL = "Resolved Website Source"
DISCOVERY_CONFIDENCE_COL = "Website Discovery Confidence"
DISCOVERY_NOTES_COL = "Website Discovery Notes"


def _is_value(value: object) -> bool:
    return str(value or "").strip().lower() not in EMPTY_VALUES


def _normal_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _tokens(value: object) -> set[str]:
    stop = {"the", "llc", "inc", "ltd", "co", "company", "auto", "automotive", "cars", "car", "dealer", "dealership"}
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").lower()) if token not in stop}


def _zip(value: object) -> str:
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return match.group(1) if match else ""


def _phone_digits(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else ""


def _host_is_directory(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == directory or host.endswith("." + directory) for directory in DIRECTORY_HOSTS)


def _url_name_score(dealer_name: str, website: str) -> tuple[int, str]:
    """Return conservative evidence that a candidate URL belongs to this dealer."""
    parsed = urlparse(website)
    host_and_path = f"{parsed.netloc}{parsed.path}".lower()
    dealer_key = _normal_text(dealer_name)
    url_key = _normal_text(host_and_path)
    if dealer_key and dealer_key in url_key:
        return 30, "full dealer name appears in URL"

    hostname = parsed.netloc.lower().removeprefix("www.")
    host_key = _normal_text(hostname)
    ratio = SequenceMatcher(None, dealer_key, host_key).ratio()
    if ratio >= 0.85:
        return 25, f"dealer/domain similarity={ratio:.2f}"

    overlap = _tokens(dealer_name) & _tokens(hostname.replace(".", " ").replace("-", " "))
    if len(overlap) >= 2:
        return min(20, len(overlap) * 8), "multiple dealer tokens appear in domain"
    return 0, "no strong dealer/domain match"


def _is_captcha_page(url: str, timeout: float) -> bool:
    """Use a small direct check only after the normal fetch was blocked."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DealerWebsiteDiscovery/1.0)"},
            timeout=min(timeout, 10.0),
            allow_redirects=True,
        )
        body = response.text.lower()
    except requests.RequestException:
        return False
    return any(marker in body for marker in CAPTCHA_MARKERS)


def _candidate_score(
    dealer_name: str,
    dealer_address: str,
    dealer_phone: str,
    place: dict[str, Any],
) -> tuple[int, str]:
    """Score one Places candidate.  Name agreement is mandatory downstream."""
    candidate_name = str(place.get("displayName", {}).get("text", ""))
    candidate_address = str(place.get("formattedAddress", ""))
    candidate_phone = str(place.get("nationalPhoneNumber", ""))
    name_ratio = SequenceMatcher(None, _normal_text(dealer_name), _normal_text(candidate_name)).ratio()
    overlap = _tokens(dealer_name) & _tokens(candidate_name)
    score = round(name_ratio * 60)
    notes = [f"name={name_ratio:.2f}"]
    if overlap:
        score += min(15, len(overlap) * 5)
        notes.append("name tokens match")
    dealer_zip, candidate_zip = _zip(dealer_address), _zip(candidate_address)
    if dealer_zip and dealer_zip == candidate_zip:
        score += 15
        notes.append("ZIP match")
    dealer_digits, candidate_digits = _phone_digits(dealer_phone), _phone_digits(candidate_phone)
    if dealer_digits and dealer_digits == candidate_digits:
        score += 20
        notes.append("phone match")
    return min(score, 100), "; ".join(notes)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    website: str = ""
    confidence: int = 0
    note: str = ""
    source: str = ""


class GooglePlacesFinder:
    provider_name = "Google Places API"

    def __init__(self, api_key: str, timeout: float) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def find(self, name: str, address: str, phone: str, min_confidence: int) -> DiscoveryResult:
        query = ", ".join(part for part in (name.strip(), address.strip()) if part)
        if not query:
            return DiscoveryResult(note="Missing dealer name and address")
        try:
            response = requests.post(
                PLACE_SEARCH_URL,
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK},
                json={"textQuery": query, "languageCode": "en"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            places = response.json().get("places", [])
        except requests.RequestException as exc:
            return DiscoveryResult(note=f"Places request failed: {exc}")
        except ValueError:
            return DiscoveryResult(note="Places returned invalid JSON")

        best: tuple[int, str, str] | None = None
        for place in places:
            website = str(place.get("websiteUri", "")).strip()
            if not website or _host_is_directory(website):
                continue
            score, detail = _candidate_score(name, address, phone, place)
            # The similarity floor prevents a nearby dealer with a web site
            # from becoming an otherwise high-scoring ZIP-only match.
            name_ratio = SequenceMatcher(
                None, _normal_text(name), _normal_text(place.get("displayName", {}).get("text", ""))
            ).ratio()
            if name_ratio < 0.62:
                continue
            if best is None or score > best[0]:
                best = (score, website, detail)
        if best is None:
            return DiscoveryResult(note="No verified official website returned by Places")
        score, website, detail = best
        if score < min_confidence:
            return DiscoveryResult(confidence=score, note=f"Candidate below threshold ({detail})")
        return DiscoveryResult(
            website=website,
            confidence=score,
            note=f"Google Places API; {detail}",
            source="Google Places API",
        )


def _verify_search_results(
    name: str,
    address: str,
    phone: str,
    results: list[dict[str, Any]],
    *,
    source: str,
    min_confidence: int,
    timeout: float,
) -> DiscoveryResult:
    """Verify result URLs from a web search before treating one as official."""
    best: tuple[int, str, str] | None = None
    for result in results[:3]:
        website = str(result.get("url", "")).strip()
        if not website or _host_is_directory(website):
            continue
        title = str(result.get("title", ""))
        name_ratio = SequenceMatcher(None, _normal_text(name), _normal_text(title)).ratio()
        if name_ratio < 0.55:
            continue
        score, detail = _candidate_score(
            name, address, phone,
            {"displayName": {"text": title}, "formattedAddress": "", "nationalPhoneNumber": ""},
        )
        try:
            fetched = fetch_dealer_html(website, timeout=timeout, mode="http")
        except Exception:
            fetched = None
        if not fetched:
            # A CAPTCHA prevents page-level verification. It can only be
            # accepted when both the search result and the actual URL provide
            # very strong identity evidence; ordinary fetch failures remain
            # rejected.
            if not _is_captcha_page(website, timeout):
                continue
            url_score, url_detail = _url_name_score(name, website)
            captcha_score = min(100, score + url_score)
            if url_score and captcha_score >= max(min_confidence, CAPTCHA_URL_MIN_CONFIDENCE):
                captcha_detail = f"{detail}; CAPTCHA page; {url_detail}"
                if best is None or captcha_score > best[0]:
                    best = (captcha_score, website, captcha_detail)
            continue

        # A search-result title alone is not enough. The candidate must be a
        # fetchable page that identifies the dealer itself.
        _, html = fetched
        page_tokens = _tokens(html)
        name_tokens = _tokens(name)
        if not name_tokens or len(name_tokens & page_tokens) < max(1, min(2, len(name_tokens))):
            continue
        score += 10
        detail += "; dealer name appears on site"
        if (zip_code := _zip(address)) and zip_code in html:
            score += 10
            detail += "; ZIP appears on site"
        if (phone_digits := _phone_digits(phone)) and phone_digits in re.sub(r"\D", "", html):
            score += 20
            detail += "; phone appears on site"
        if best is None or score > best[0]:
            best = (min(score, 100), website, detail)
    if best is None:
        return DiscoveryResult(note=f"No verified dealer website in {source} results")
    score, website, detail = best
    if score < min_confidence:
        return DiscoveryResult(confidence=score, note=f"Search candidate below threshold ({detail})")
    return DiscoveryResult(
        website=website,
        confidence=score,
        note=f"{source}; {detail}",
        source=source,
    )


class GoogleCustomSearchFinder:
    """Google web-search fallback for existing Custom Search JSON API users."""

    provider_name = "Google Custom Search"
    endpoint = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, search_engine_id: str, timeout: float) -> None:
        self.api_key = api_key
        self.search_engine_id = search_engine_id
        self.timeout = timeout

    def find(self, name: str, address: str, phone: str, min_confidence: int) -> DiscoveryResult:
        try:
            response = requests.get(
                self.endpoint,
                params={
                    "key": self.api_key,
                    "cx": self.search_engine_id,
                    "q": f'"{name}" "{address}"',
                    "num": 3,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            items = response.json().get("items", [])
        except requests.RequestException as exc:
            return DiscoveryResult(note=f"Google Custom Search request failed: {exc}")
        except ValueError:
            return DiscoveryResult(note="Google Custom Search returned invalid JSON")
        results = [
            {"url": item.get("link", ""), "title": item.get("title", "")}
            for item in items
        ]
        return _verify_search_results(
            name, address, phone, results,
            source="Google Custom Search", min_confidence=min_confidence, timeout=self.timeout,
        )


class ExaWebFinder:
    """Exa web-search fallback for dealers without a verified Places result."""

    provider_name = "Exa Search"

    def __init__(self, api_key: str, timeout: float) -> None:
        self.timeout = timeout
        self.client = Exa(api_key=api_key) if Exa is not None else None

    def find(self, name: str, address: str, phone: str, min_confidence: int) -> DiscoveryResult:
        if self.client is None:
            return DiscoveryResult(note="Exa Search unavailable: install exa-py")
        try:
            response = self.client.search(
                f'"{name}"',
                # f'"{name}" "{address}"',
                num_results=3,
                type="auto",
                contents={"highlights": True},
                system_prompt="we need to find the main domain of dealerships"
            )
            raw_results = getattr(response, "results", [])
            results = [
                {
                    "url": getattr(item, "url", ""),
                    "title": getattr(item, "title", ""),
                }
                for item in raw_results
            ]
        except Exception as exc:
            return DiscoveryResult(note=f"Exa Search request failed: {exc}")

        return _verify_search_results(
            name, address, phone, results,
            source="Exa Search", min_confidence=min_confidence, timeout=self.timeout,
        )


class TavilyWebFinder:
    """Tavily web-search fallback for dealers without a verified Places result."""

    provider_name = "Tavily Search"

    def __init__(self, api_key: str, timeout: float) -> None:
        self.timeout = timeout
        self.client = TavilyClient(api_key=api_key) if TavilyClient is not None else None

    def find(self, name: str, address: str, phone: str, min_confidence: int) -> DiscoveryResult:
        if self.client is None:
            return DiscoveryResult(note="Tavily Search unavailable: install tavily-python")
        try:
            response = self.client.search(
                query=f'"{name}" "{address}"',
                search_depth="advanced",
                max_results=3,
                include_answer=False,
                include_raw_content=False,
                topic="general",
            )
            results = response.get("results", [])
        except Exception as exc:
            return DiscoveryResult(note=f"Tavily Search request failed: {exc}")

        return _verify_search_results(
            name, address, phone, results,
            source="Tavily Search", min_confidence=min_confidence, timeout=self.timeout,
        )


class BraveWebFinder:
    """Independent web-search fallback for dealers that have no Maps website."""

    provider_name = "Brave Search"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: float) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def find(self, name: str, address: str, phone: str, min_confidence: int) -> DiscoveryResult:
        query = f'"{name}" "{address}"'
        try:
            response = requests.get(
                self.endpoint,
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                params={"q": query, "count": 10, "country": "US", "search_lang": "en"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            results = response.json().get("web", {}).get("results", [])
        except requests.RequestException as exc:
            return DiscoveryResult(note=f"Brave Search request failed: {exc}")
        except ValueError:
            return DiscoveryResult(note="Brave Search returned invalid JSON")

        return _verify_search_results(
            name, address, phone, results,
            source="Brave Search", min_confidence=min_confidence, timeout=self.timeout,
        )


def _first_column(df: pd.DataFrame, choices: tuple[str, ...]) -> str | None:
    lookup = {str(col).strip().lower(): str(col) for col in df.columns}
    return next((lookup[choice.lower()] for choice in choices if choice.lower() in lookup), None)


def _read_csv(path: Path) -> pd.DataFrame:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        sample = handle.read(65536)
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",|;\t").delimiter
    except csv.Error:
        delimiter = ","
    return pd.read_csv(path, sep=delimiter, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, dtype=str, keep_default_na=False)
    raise ValueError(f"Unsupported input: {path}")


def _write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        df.to_csv(path, index=False, encoding="utf-8")
    elif path.suffix.lower() in {".xlsx", ".xlsm"}:
        df.to_excel(path, index=False)
    else:
        raise ValueError("Output must be .csv or .xlsx")


def discover_file(path: Path, output: Path, finders: list[Any], args: argparse.Namespace) -> None:
    df = _read_table(path)
    name_col = args.name_col or _first_column(df, ("Name", "Dealer Name", "Dealership Name"))
    address_col = args.address_col or _first_column(df, ("List Address", "Address", "Dealer Address"))
    phone_col = args.phone_col or _first_column(df, ("Google Map Phone", "Website Phone", "Phone", "Cargurus Phone"))
    if not name_col or not address_col:
        raise ValueError("Could not find Name and Address columns; pass --name-col and --address-col")

    website_cols = [
        col
        for col in (RESOLVED_WEBSITE_COL, "Website", "Google Map Website")
        if col in df.columns
    ]
    for col in (RESOLVED_WEBSITE_COL, RESOLVED_SOURCE_COL, DISCOVERY_CONFIDENCE_COL, DISCOVERY_NOTES_COL):
        if col not in df.columns:
            df[col] = ""

    pending: list[int] = []
    for idx in df.index:
        existing = next((str(df.at[idx, col]).strip() for col in website_cols if _is_value(df.at[idx, col])), "")
        if existing:
            source = next(col for col in website_cols if _is_value(df.at[idx, col]))
            if source == RESOLVED_WEBSITE_COL and _is_value(df.at[idx, RESOLVED_SOURCE_COL]):
                source = str(df.at[idx, RESOLVED_SOURCE_COL]).strip()
            df.at[idx, RESOLVED_WEBSITE_COL] = existing
            df.at[idx, RESOLVED_SOURCE_COL] = source
            df.at[idx, DISCOVERY_CONFIDENCE_COL] = "100"
            df.at[idx, DISCOVERY_NOTES_COL] = "Existing website retained"
        else:
            pending.append(idx)

    def task(idx: int) -> tuple[int, DiscoveryResult]:
        name = str(df.at[idx, name_col])
        address = str(df.at[idx, address_col])
        phone = str(df.at[idx, phone_col]) if phone_col else ""
        failed_notes: list[str] = []
        for finder in finders:
            result = finder.find(name, address, phone, args.min_confidence)
            if result.website:
                return idx, result
            provider_name = getattr(finder, "provider_name", finder.__class__.__name__)
            note = result.note or "no verified result"
            failed_notes.append(f"{provider_name}: {note}")
            log.debug("%s did not resolve %r: %s", provider_name, name, note)
        return idx, DiscoveryResult(
            note=" | ".join(failed_notes) or "No discovery provider configured"
        )

    found = 0
    found_by_source: Counter[str] = Counter()
    with ThreadPoolExecutor(max_workers=max(1, args.threads)) as pool:
        futures = {pool.submit(task, idx): idx for idx in pending}
        for future in tqdm(as_completed(futures), total=len(futures), desc=path.name, unit="dealer"):
            idx, result = future.result()
            df.at[idx, DISCOVERY_CONFIDENCE_COL] = str(result.confidence) if result.confidence else ""
            df.at[idx, DISCOVERY_NOTES_COL] = result.note
            if result.website:
                df.at[idx, RESOLVED_WEBSITE_COL] = result.website
                df.at[idx, RESOLVED_SOURCE_COL] = result.source or "Discovery provider"
                found += 1
                found_by_source[result.source or "Discovery provider"] += 1

    _write_table(df, output)
    source_summary = ", ".join(
        f"{source}={count}"
        for source, count in sorted(found_by_source.items())
    ) or "none"
    log.info(
        "%s: %s existing, %s newly discovered (%s), %s still missing -> %s",
        path.name,
        len(df) - len(pending),
        found,
        source_summary,
        len(pending) - found,
        output,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover verified dealership websites via Places and web search APIs")
    parser.add_argument("input", help="CSV/XLSX file or directory of files")
    parser.add_argument("-o", "--output", required=True, help="Output file, or output directory for directory input")
    parser.add_argument("--google-places-api-key", default=os.getenv("GOOGLE_MAPS_API_KEY", ""), help="Google Places API key (or set GOOGLE_MAPS_API_KEY)")
    parser.add_argument("--google-custom-search-api-key", default=os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY", ""), help="Google Custom Search JSON API key (or set GOOGLE_CUSTOM_SEARCH_API_KEY)")
    parser.add_argument("--google-custom-search-cx", default=os.getenv("GOOGLE_CUSTOM_SEARCH_CX", ""), help="Google Programmable Search Engine ID (or set GOOGLE_CUSTOM_SEARCH_CX)")
    parser.add_argument("--exa-api-key", default=os.getenv("EXA_API_KEY", ""), help="Exa Search API key (or set EXA_API_KEY)")
    parser.add_argument("--tavily-api-key", default=os.getenv("TAVILY_API_KEY", ""), help="Tavily Search API key (or set TAVILY_API_KEY)")
    parser.add_argument("--brave-search-api-key", default=os.getenv("BRAVE_SEARCH_API_KEY", ""), help="Optional independent Brave Search API key (or set BRAVE_SEARCH_API_KEY)")
    parser.add_argument("--name-col")
    parser.add_argument("--address-col")
    parser.add_argument("--phone-col")
    parser.add_argument("--min-confidence", type=int, default=75, help="Minimum score before a website is accepted (default: 75)")
    parser.add_argument("-t", "--threads", type=int, default=4, help="Concurrent API requests (default: 4)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("-v", "--verbose", action="store_true", help="Log every provider fallback attempt")
    args = parser.parse_args()
    if bool(args.google_custom_search_api_key) != bool(args.google_custom_search_cx):
        parser.error("Google Custom Search requires both --google-custom-search-api-key and --google-custom-search-cx")
    if not (args.google_places_api_key or args.google_custom_search_api_key or args.exa_api_key or args.tavily_api_key or args.brave_search_api_key):
        parser.error("provide a Google Places, Google Custom Search, Exa, Tavily, or Brave Search API key")
    if not 0 <= args.min_confidence <= 100:
        parser.error("--min-confidence must be between 0 and 100")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    source = Path(args.input)
    if source.is_file():
        files = [source]
        output_paths = [Path(args.output)]
    elif source.is_dir():
        files = sorted(p for p in source.iterdir() if p.suffix.lower() in {".csv", ".xlsx", ".xlsm", ".xls"})
        if not files:
            raise SystemExit(f"No CSV/XLSX files in {source}")
        out_dir = Path(args.output)
        output_paths = [out_dir / path.name for path in files]
    else:
        raise SystemExit(f"Input not found: {source}")
    finders: list[Any] = []
    if args.google_places_api_key:
        finders.append(GooglePlacesFinder(args.google_places_api_key, args.timeout))
    if args.exa_api_key:
        finders.append(ExaWebFinder(args.exa_api_key, args.timeout))
    if args.tavily_api_key:
        finders.append(TavilyWebFinder(args.tavily_api_key, args.timeout))
    if args.google_custom_search_api_key:
        finders.append(
            GoogleCustomSearchFinder(
                args.google_custom_search_api_key,
                args.google_custom_search_cx,
                args.timeout,
            )
        )
    if args.brave_search_api_key:
        finders.append(BraveWebFinder(args.brave_search_api_key, args.timeout))
    log.info(
        "Discovery providers (in order): %s",
        " -> ".join(getattr(finder, "provider_name", finder.__class__.__name__) for finder in finders),
    )
    if args.exa_api_key and Exa is None:
        log.warning("Exa key is configured but exa-py is not installed; run: pip install -r requirements.txt")
    for file, output in zip(files, output_paths):
        discover_file(file, output, finders, args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        log.error("%s", exc)
        sys.exit(1)
