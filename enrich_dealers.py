#!/usr/bin/env python3
"""
Enrich dealership Excel/CSV files with website provider, phone, email, chat widget,
360° vehicle viewers, customer AI, and dealer type from dealer sites and names.

Every input row is written to the enriched output.
Failed website lookups include a note in Website Enrichment Notes explaining why.

Split work across terminals with -W (total workers) and -w (this worker, 0..N-1).
Multiple input files are split by file; a single file is split by state column or by row.
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import logging
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import pandas as pd
from openpyxl import Workbook
from tqdm import tqdm

from dealer_chat_widget import detect_chat_widgets
from dealer_360_imaging import detect_360_viewers
from dealer_customer_ai import detect_customer_ai
from dealer_email import extract_primary_email
from dealer_phone import extract_primary_phone
from dealer_platforms import DEALER_PLATFORMS
from dealer_type import classify_dealer_type
from dealer_fetch import (
    FetchMode,
    fetch_dealer_html,
    fetch_dealer_html_with_resources,
    normalize_dealer_url,
)
from website_provider import detect_from_html

log = logging.getLogger("enrich_dealers")

WEBSITE_COLUMN_CANDIDATES = (
    "resolved website",
    "website",
    "google map website",
    "discovered website",
    "dealer website",
    "dealerwebsite",
    "website url",
    "website_url",
    "dealer url",
    "dealer_url",
    "url",
    "web site",
    "site",
)

STATE_COLUMN_CANDIDATES = (
    "state",
    "st",
    "dealer state",
    "province",
    "region",
)

NAME_COLUMN_CANDIDATES = (
    "dealer name",
    "dealername",
    "dealership name",
    "dealership",
    "name",
    "dealer",
    "business name",
    "company name",
    "store name",
)

OUTPUT_PROVIDER_COL = "Website Provider"
OUTPUT_PHONE_COL = "Website Phone"
OUTPUT_EMAIL_COL = "Website Email"
OUTPUT_CHAT_WIDGET_COL = "Chat Widget"
OUTPUT_360_VIEWER_COL = "360° Vehicle Viewer"
OUTPUT_CUSTOMER_AI_COL = "Customer AI"
OUTPUT_DEALER_TYPE_COL = "Dealer Type"
OUTPUT_NOTES_COL = "Website Enrichment Notes"

ENRICHMENT_COLS = (
    OUTPUT_PROVIDER_COL,
    OUTPUT_PHONE_COL,
    OUTPUT_EMAIL_COL,
    OUTPUT_CHAT_WIDGET_COL,
    OUTPUT_360_VIEWER_COL,
    OUTPUT_CUSTOMER_AI_COL,
    OUTPUT_DEALER_TYPE_COL,
    OUTPUT_NOTES_COL,
)

# These fields require the dealer page to be loaded.  Dealer Type is handled
# from the dealership name and Website Enrichment Notes can be derived from the
# values already present in the row.
WEBSITE_FETCH_COLS = (
    OUTPUT_PROVIDER_COL,
    OUTPUT_PHONE_COL,
    OUTPUT_EMAIL_COL,
    OUTPUT_CHAT_WIDGET_COL,
    OUTPUT_360_VIEWER_COL,
    OUTPUT_CUSTOMER_AI_COL,
)

REASON_NO_WEBSITE = "No dealer website provided"
REASON_SITE_NOT_LOADED = "Website could not be loaded"
REASON_PROVIDER_NOT_FOUND = "Website provider not detected on site"
REASON_PHONE_NOT_FOUND = "Phone number not found on website"
REASON_EMAIL_NOT_FOUND = "Email address not found on website"

SUPPORTED_INPUT_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls", ".csv"})
DEFAULT_CSV_SEP = ","
ENRICHED_OUTPUT_DIR = "enriched_v5"

_VDP_PATH_HINTS = re.compile(
    r"(?:/vehicle|/inventory|/vdp(?:/|$)|/details?(?:/|$)|/cars-for-sale|/used-|/new-)",
    re.I,
)
_NON_HTML_PATH = re.compile(r"\.(?:pdf|jpg|jpeg|png|gif|webp|svg|zip)(?:$|[?#])", re.I)
_GENERIC_RESULTS = {
    "Generic chat widget",
    "Generic 360° viewer",
    "AI customer assistant (vendor unknown)",
}


def _find_state_column(df: pd.DataFrame, override: str | None) -> str | None:
    if override:
        return _resolve_column(df, override, required=True)
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for key in STATE_COLUMN_CANDIDATES:
        if key in lower_map:
            return lower_map[key]
    for col in df.columns:
        if "state" in str(col).lower():
            return col
    return None


def _normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip BOM/whitespace from headers (common in Excel exports)."""
    out = df.copy()
    out.columns = [str(c).replace("\ufeff", "").strip() for c in out.columns]
    return out


def _resolve_column(df: pd.DataFrame, name: str, *, required: bool = True) -> str | None:
    """Match a column by exact name, then case-insensitive stripped name."""
    wanted = name.strip()
    if wanted in df.columns:
        return wanted
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    found = lower_map.get(wanted.lower())
    if found:
        return found
    if required:
        raise ValueError(f"Column not found: {name!r}. Available: {list(df.columns)}")
    return None


def _find_name_column(df: pd.DataFrame, override: str | None) -> str | None:
    if override:
        return _resolve_column(df, override, required=True)
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for key in NAME_COLUMN_CANDIDATES:
        if key in lower_map:
            return lower_map[key]
    for col in df.columns:
        low = str(col).lower()
        if "dealer" in low and "name" in low:
            return col
        if low in ("name", "dealership"):
            return col
    return None


def _find_website_column(df: pd.DataFrame, override: str | None) -> str:
    if override:
        return _resolve_column(df, override, required=True)  # type: ignore[return-value]

    excluded = {
        OUTPUT_PROVIDER_COL.lower(),
        OUTPUT_PHONE_COL.lower(),
        OUTPUT_EMAIL_COL.lower(),
        OUTPUT_CHAT_WIDGET_COL.lower(),
        OUTPUT_360_VIEWER_COL.lower(),
        OUTPUT_CUSTOMER_AI_COL.lower(),
        OUTPUT_DEALER_TYPE_COL.lower(),
        OUTPUT_NOTES_COL.lower(),
    }
    lower_map = {
        str(c).strip().lower(): c
        for c in df.columns
        if str(c).strip().lower() not in excluded
    }

    for key in WEBSITE_COLUMN_CANDIDATES:
        if key in lower_map:
            return lower_map[key]

    for col in df.columns:
        low = str(col).strip().lower()
        if low in excluded:
            continue
        if "website" in low or low.endswith(" url") or low == "url":
            return col
    raise ValueError(
        "Could not detect website column. Use --website-col. "
        f"Columns: {list(df.columns)}"
    )


def _serialize_cell(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    return str(value)


def _exclude_output_column(col: str) -> bool:
    """Drop status / worker columns from enriched outputs (not re-emitted)."""
    low = str(col).strip().lower()
    if low in ("process id", "process_id", "pid", "worker", "worker id", "worker_id"):
        return True
    return False


def _output_columns(df: pd.DataFrame) -> list[str]:
    cols = [c for c in df.columns if not _exclude_output_column(c)]
    for col in ENRICHMENT_COLS:
        if col not in cols:
            cols.append(col)
    return cols


class IncrementalWriter:
    """Append one dealership row at a time to CSV or Excel."""

    def __init__(self, path: Path, columns: list[str]) -> None:
        self.path = path
        self.columns = columns
        self._lock = threading.Lock()
        self._count = 0
        suffix = path.suffix.lower()

        if suffix == ".csv":
            self._mode = "csv"
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._csv = csv.DictWriter(
                self._file,
                fieldnames=columns,
                extrasaction="ignore",
            )
            self._csv.writeheader()
            self._file.flush()
            self._wb = None
            self._ws = None
        elif suffix in (".xlsx", ".xlsm"):
            self._mode = "xlsx"
            self._file = None
            self._csv = None
            self._wb = Workbook()
            self._ws = self._wb.active
            self._ws.append(columns)
            self._wb.save(path)
        else:
            raise ValueError(f"Unsupported output format: {path}")

    def append(self, row: dict[str, Any]) -> None:
        values = {col: _serialize_cell(row.get(col, "")) for col in self.columns}
        with self._lock:
            if self._mode == "csv":
                assert self._csv is not None and self._file is not None
                self._csv.writerow(values)
                self._file.flush()
            else:
                assert self._wb is not None and self._ws is not None
                self._ws.append([values[col] for col in self.columns])
                self._wb.save(self.path)
            self._count += 1

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    @property
    def count(self) -> int:
        return self._count


def _enrichment_notes(
    *,
    has_website: bool,
    loaded: bool,
    provider: str,
    phone: str,
    email: str,
) -> str:
    """Human-readable reasons when website fields could not be enriched."""
    if not has_website:
        return REASON_NO_WEBSITE
    if not loaded:
        return REASON_SITE_NOT_LOADED

    reasons: list[str] = []
    if not provider:
        reasons.append(REASON_PROVIDER_NOT_FOUND)
    if not phone:
        reasons.append(REASON_PHONE_NOT_FOUND)
    if not email:
        reasons.append(REASON_EMAIL_NOT_FOUND)
    return "; ".join(reasons)


def _make_enrichment(
    *,
    provider: str = "",
    phone: str = "",
    email: str = "",
    chat_widget: str = "",
    vehicle_viewer: str = "",
    customer_ai: str = "",
    dealer_type: str = "",
    has_website: bool = True,
    loaded: bool = True,
) -> dict[str, str]:
    return {
        OUTPUT_PROVIDER_COL: provider,
        OUTPUT_PHONE_COL: phone,
        OUTPUT_EMAIL_COL: email,
        OUTPUT_CHAT_WIDGET_COL: chat_widget,
        OUTPUT_360_VIEWER_COL: vehicle_viewer,
        OUTPUT_CUSTOMER_AI_COL: customer_ai,
        OUTPUT_DEALER_TYPE_COL: dealer_type,
        OUTPUT_NOTES_COL: _enrichment_notes(
            has_website=has_website,
            loaded=loaded,
            provider=provider,
            phone=phone,
            email=email,
        ),
    }


def _has_enrichment_value(value: object) -> bool:
    """True for a real existing cell value that must not be overwritten."""
    return bool(_serialize_cell(value).strip())


def _existing_enrichment(df: pd.DataFrame, idx: int) -> dict[str, str]:
    """Read only the enrichment cells already supplied on this input row."""
    return {
        col: _serialize_cell(df.at[idx, col]) if col in df.columns else ""
        for col in ENRICHMENT_COLS
    }


def _needs_website_fetch(existing: dict[str, str]) -> bool:
    """Only fetch when at least one page-derived field is still empty."""
    return any(not _has_enrichment_value(existing[field]) for field in WEBSITE_FETCH_COLS)


def _merge_enrichment(
    existing: dict[str, str],
    generated: dict[str, str],
    *,
    has_website: bool,
    loaded: bool,
) -> dict[str, str]:
    """Keep populated input values; fill only empty cells from this run."""
    merged = {
        col: existing[col] if _has_enrichment_value(existing.get(col, "")) else generated.get(col, "")
        for col in ENRICHMENT_COLS
    }
    # Notes follow the same non-overwrite rule. When they were absent, generate
    # them from the final (possibly partly pre-existing) provider/phone/email.
    if not _has_enrichment_value(existing.get(OUTPUT_NOTES_COL, "")):
        merged[OUTPUT_NOTES_COL] = _enrichment_notes(
            has_website=has_website,
            loaded=loaded,
            provider=merged[OUTPUT_PROVIDER_COL],
            phone=merged[OUTPUT_PHONE_COL],
            email=merged[OUTPUT_EMAIL_COL],
        )
    return merged


def _dealer_type_for_row(df: pd.DataFrame, idx: int, name_col: str | None) -> str:
    if not name_col:
        return ""
    val = df.at[idx, name_col]
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return classify_dealer_type(str(val))


def _site_host(url: str) -> str:
    """Comparable host that treats www.example.com as example.com."""
    return urlparse(url).netloc.lower().split(":", 1)[0].removeprefix("www.")


def _detection_html(html: str, resource_urls: set[str]) -> str:
    """Expose runtime resource domains to the existing HTML-based detectors."""
    if not resource_urls:
        return html
    resource_tags = "\n".join(
        f'<script src="{html_lib.escape(url, quote=True)}"></script>'
        for url in sorted(resource_urls)
    )
    return f"{html}\n<!-- browser-loaded resources -->\n{resource_tags}"


def _vehicle_detail_urls(html: str, base_url: str, *, limit: int) -> list[str]:
    """Return a small, same-site sample of likely vehicle-detail page URLs."""
    if limit <= 0:
        return []
    base_host = _site_host(base_url)
    found: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r'<a\b[^>]*\bhref=["\']([^"\']+)', html or "", re.I):
        absolute, _ = urldefrag(urljoin(base_url, html_lib.unescape(raw).strip()))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or _site_host(absolute) != base_host:
            continue
        if not _VDP_PATH_HINTS.search(parsed.path) or _NON_HTML_PATH.search(absolute):
            continue
        # Finance/share/filter links can contain inventory words without being a VDP.
        if any(word in parsed.path.lower() for word in ("/contact", "/finance", "/service", "/parts")):
            continue
        canonical = parsed._replace(query="", fragment="").geturl()
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
            if len(found) >= limit:
                break
    return found


def _combine_detection_values(values: list[str]) -> str:
    """Merge page-level detections, preferring a named provider over generic."""
    entries: list[str] = []
    for value in values:
        for part in (value or "").split(","):
            part = part.strip()
            if part and part not in entries:
                entries.append(part)
    named = [entry for entry in entries if entry not in _GENERIC_RESULTS]
    return ", ".join(named or entries)


def _process_row(
    website: str,
    *,
    existing: dict[str, str],
    timeout: float,
    fetch_mode: str,
    headed: bool,
    deep_detection: bool = False,
    vdp_sample_size: int = 3,
) -> tuple[dict[str, str], bool]:
    """Fetch dealer site; return (enrichment fields, site_loaded)."""
    base = normalize_dealer_url(str(website) if website is not None else "")
    if not base:
        return (
            _merge_enrichment(
                existing,
                _make_enrichment(has_website=False, loaded=False),
                has_website=False,
                loaded=False,
            ),
            False,
        )

    needs_deep_detectors = any(
        not _has_enrichment_value(existing[col])
        for col in (OUTPUT_CHAT_WIDGET_COL, OUTPUT_360_VIEWER_COL, OUTPUT_CUSTOMER_AI_COL)
    )
    if deep_detection and needs_deep_detectors:
        fetched_with_resources = fetch_dealer_html_with_resources(
            base,
            timeout=timeout,
            mode=fetch_mode,
            headed=headed,
            force_browser=True,
        )
        fetched = (
            (fetched_with_resources[0], fetched_with_resources[1])
            if fetched_with_resources else None
        )
        homepage_resources = fetched_with_resources[2] if fetched_with_resources else set()
    else:
        fetched = fetch_dealer_html(
            base,
            timeout=timeout,
            mode=fetch_mode,
            headed=headed,
        )
        homepage_resources: set[str] = set()
    if not fetched:
        log.debug("site not loaded: %s", base)
        return (
            _merge_enrichment(
                existing,
                _make_enrichment(loaded=False),
                has_website=True,
                loaded=False,
            ),
            False,
        )

    final_url, html = fetched
    detection_pages: list[str] = [_detection_html(html, homepage_resources)]

    if deep_detection and needs_deep_detectors:
        vdp_urls = _vehicle_detail_urls(html, final_url, limit=vdp_sample_size)
        for vdp_url in vdp_urls:
            vdp = fetch_dealer_html_with_resources(
                vdp_url,
                timeout=timeout,
                mode=fetch_mode,
                headed=headed,
            )
            if vdp:
                vdp_final_url, vdp_html, vdp_resources = vdp
                detection_pages.append(_detection_html(vdp_html, vdp_resources))
                log.debug("deep scan sampled %s", vdp_final_url)
        log.debug("deep scan %s: homepage + %s vehicle pages", final_url, len(detection_pages) - 1)

    provider_name = ""
    if not _has_enrichment_value(existing[OUTPUT_PROVIDER_COL]):
        provider_match = detect_from_html(html, source_url=final_url)
        if provider_match and provider_match.display_name in DEALER_PLATFORMS:
            provider_name = provider_match.display_name

    phone = (
        extract_primary_phone(html) or ""
        if not _has_enrichment_value(existing[OUTPUT_PHONE_COL])
        else ""
    )
    email = (
        extract_primary_email(html) or ""
        if not _has_enrichment_value(existing[OUTPUT_EMAIL_COL])
        else ""
    )
    chat_widget = (
        _combine_detection_values([detect_chat_widgets(page) for page in detection_pages])
        if not _has_enrichment_value(existing[OUTPUT_CHAT_WIDGET_COL])
        else ""
    )
    vehicle_viewer = (
        _combine_detection_values([detect_360_viewers(page) for page in detection_pages])
        if not _has_enrichment_value(existing[OUTPUT_360_VIEWER_COL])
        else ""
    )
    customer_ai = (
        _combine_detection_values([detect_customer_ai(page) for page in detection_pages])
        if not _has_enrichment_value(existing[OUTPUT_CUSTOMER_AI_COL])
        else ""
    )

    return (
        _merge_enrichment(
            existing,
            _make_enrichment(
                provider=provider_name,
                phone=phone,
                email=email,
                chat_widget=chat_widget,
                vehicle_viewer=vehicle_viewer,
                customer_ai=customer_ai,
                loaded=True,
            ),
            has_website=True,
            loaded=True,
        ),
        True,
    )



def _build_output_row(df: pd.DataFrame, idx: int, enrichment: dict[str, Any]) -> dict[str, Any]:
    row = {col: df.at[idx, col] for col in df.columns}
    row.update(enrichment)
    return row


def _shard_input_paths(paths: list[Path], worker: int, total_workers: int) -> list[Path]:
    """Assign input files to worker ``worker`` of ``total_workers`` (sorted, round-robin)."""
    if total_workers <= 1:
        return paths
    return [p for i, p in enumerate(paths) if i % total_workers == worker]


def _apply_worker_shard(
    df: pd.DataFrame,
    worker: int,
    total_workers: int,
    *,
    state_col: str | None,
) -> tuple[pd.DataFrame, str]:
    """Subset rows for this worker (by state list, else every Nth row)."""
    if total_workers <= 1:
        return df, "all rows"

    if state_col is not None:
        series = df[state_col].astype(str).str.strip()
        states = sorted(s for s in series.dropna().unique() if s and s.lower() != "nan")
        assigned = [s for i, s in enumerate(states) if i % total_workers == worker]
        if not assigned:
            return df.iloc[0:0], "no states assigned"
        mask = series.isin(assigned)
        label = ", ".join(assigned[:8]) + ("..." if len(assigned) > 8 else "")
        return df.loc[mask], f"states: {label}"

    subset = df.iloc[worker::total_workers]
    return subset, f"row slice {worker} of {total_workers} (every {total_workers}th row)"


def _validate_worker_args(worker: int, total_workers: int) -> None:
    if total_workers < 1:
        raise ValueError(f"-W must be >= 1, got {total_workers}")
    if worker < 0 or worker >= total_workers:
        raise ValueError(f"-w must be between 0 and {total_workers - 1}, got {worker}")


def enrich_file(
    input_path: Path,
    output_path: Path,
    *,
    website_col: str | None,
    name_col: str | None,
    state_col: str | None,
    threads: int,
    timeout: float,
    csv_sep: str = DEFAULT_CSV_SEP,
    worker: int = 0,
    total_workers: int = 1,
    shard_rows: bool = False,
    fetch_mode: str = FetchMode.AUTO.value,
    headed: bool = False,
    deep_detection: bool = False,
    vdp_sample_size: int = 3,
) -> None:
    if deep_detection and threads > 2:
        log.warning(
            "Deep detection launches a browser per dealer; use -t 1 or -t 2 (currently %s)",
            threads,
        )
    elif fetch_mode in (FetchMode.BROWSER.value, FetchMode.AUTO.value) and threads > 2:
        log.warning(
            "Browser fetch with %s threads can be unstable; use -t 1 or -t 2 for browser/auto",
            threads,
        )

    df = _read_table(input_path, csv_sep=csv_sep)
    total_rows = len(df)

    if shard_rows and total_workers > 1:
        state_column = _find_state_column(df, state_col)
        df, shard_desc = _apply_worker_shard(df, worker, total_workers, state_col=state_column)
        log.info(
            "Worker %s/%s on %s: %s (%s of %s rows)",
            worker + 1,
            total_workers,
            input_path.name,
            shard_desc,
            len(df),
            total_rows,
        )
        if df.empty:
            log.warning("Worker %s/%s: no rows in shard; skipping file", worker + 1, total_workers)
            return

    col = _find_website_column(df, website_col)
    name_column = _find_name_column(df, name_col)
    log.info("Input %s: %s rows, website column %r", input_path.name, len(df), col)
    if deep_detection:
        log.info("Deep detection enabled: browser resources + up to %s vehicle-detail pages/site", vdp_sample_size)
    if name_column:
        log.info("Dealer type from name column %r", name_column)
    else:
        log.warning("No dealer name column found; Dealer Type will be empty (use --name-col)")

    if df.empty:
        log.warning("No rows in %s", input_path.name)

    enrichments: dict[int, dict[str, str]] = {}
    rows_with_url: list[tuple[int, str, str, dict[str, str]]] = []
    no_website = 0
    already_complete = 0

    for idx, val in df[col].items():
        existing = _existing_enrichment(df, idx)
        if not _has_enrichment_value(existing[OUTPUT_DEALER_TYPE_COL]):
            existing[OUTPUT_DEALER_TYPE_COL] = _dealer_type_for_row(df, idx, name_column)
        url = normalize_dealer_url(str(val) if pd.notna(val) else "")
        if not url:
            enrichments[idx] = _merge_enrichment(
                existing,
                _make_enrichment(has_website=False, loaded=False),
                has_website=False,
                loaded=False,
            )
            no_website += 1
            continue

        if not _needs_website_fetch(existing):
            # No network request or detector call is needed for a fully
            # enriched website row.
            enrichments[idx] = _merge_enrichment(
                existing,
                _make_enrichment(),
                has_website=True,
                loaded=True,
            )
            already_complete += 1
            continue

        rows_with_url.append((idx, str(val), fetch_mode, existing))

    def task(item: tuple[int, str, str, dict[str, str]]) -> tuple[int, dict[str, str], bool]:
        idx, url, row_fetch_mode, existing = item
        enrichment, loaded = _process_row(
            url,
            existing=existing,
            timeout=timeout,
            fetch_mode=row_fetch_mode,
            headed=headed,
            deep_detection=deep_detection,
            vdp_sample_size=vdp_sample_size,
        )
        return idx, enrichment, loaded

    unloaded = 0
    if rows_with_url:
        with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
            futures = {pool.submit(task, item): item[0] for item in rows_with_url}
            for fut in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=input_path.name,
                unit="site",
            ):
                idx, enrichment, loaded = fut.result()
                enrichments[idx] = enrichment
                if not loaded:
                    unloaded += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_columns = _output_columns(df)
    writer = IncrementalWriter(output_path, out_columns)
    try:
        for idx in df.index:
            row_enrichment = enrichments.get(
                idx,
                _merge_enrichment(
                    _existing_enrichment(df, idx),
                    _make_enrichment(has_website=False, loaded=False),
                    has_website=False,
                    loaded=False,
                ),
            )
            writer.append(_build_output_row(df, idx, row_enrichment))
    finally:
        writer.close()

    log.info(
        "Wrote %s (%s rows: %s no website, %s already complete, %s fetched, %s site not loaded)",
        output_path,
        writer.count,
        no_website,
        already_complete,
        len(rows_with_url),
        unloaded,
    )


def _sniff_csv_delimiter(path: Path, *, encoding: str) -> str:
    with open(path, newline="", encoding=encoding, errors="replace") as f:
        sample = f.read(65536)
    try:
        return csv.Sniffer().sniff(sample, delimiters="|,;\t").delimiter
    except csv.Error:
        return DEFAULT_CSV_SEP


def _read_csv(path: Path, *, sep: str = DEFAULT_CSV_SEP) -> pd.DataFrame:
    """Read dealer CSV; pick delimiter that yields the most columns."""
    last_error: Exception | None = None
    best_df: pd.DataFrame | None = None
    best_cols = 0
    best_meta: tuple[str, str, str] | None = None

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        sniffed = _sniff_csv_delimiter(path, encoding=encoding)
        attempts: list[tuple[str, str, str | None]] = [
            (sniffed, "python", "warn"),
            (",", "python", "warn"),
            (sep, "c", None),
            (";", "python", "warn"),
            ("\t", "python", "warn"),
        ]
        seen: set[tuple[str, str, str | None]] = set()
        for attempt_sep, engine, on_bad_lines in attempts:
            key = (attempt_sep, engine, on_bad_lines)
            if key in seen:
                continue
            seen.add(key)

            kwargs: dict[str, Any] = {
                "filepath_or_buffer": path,
                "dtype": str,
                "encoding": encoding,
                "sep": attempt_sep,
                "engine": engine,
            }
            if on_bad_lines is not None:
                kwargs["on_bad_lines"] = on_bad_lines

            try:
                df = _normalize_dataframe_columns(pd.read_csv(**kwargs))
            except UnicodeDecodeError as exc:
                last_error = exc
                break
            except pd.errors.ParserError as exc:
                last_error = exc
                log.debug(
                    "CSV parse failed for %s (encoding=%s, sep=%r, engine=%s): %s",
                    path.name,
                    encoding,
                    attempt_sep,
                    engine,
                    exc,
                )
                continue

            ncols = len(df.columns)
            if ncols > best_cols:
                best_df = df
                best_cols = ncols
                best_meta = (encoding, attempt_sep, engine)

            # Dealer exports usually have many columns; stop early on a good parse.
            if ncols >= 8:
                log.info(
                    "Parsed %s with encoding=%s, sep=%r, engine=%s (%s columns)",
                    path.name,
                    encoding,
                    attempt_sep,
                    engine,
                    ncols,
                )
                return df

    if best_df is not None and best_meta is not None:
        encoding, attempt_sep, engine = best_meta
        log.info(
            "Parsed %s with encoding=%s, sep=%r, engine=%s (%s columns)",
            path.name,
            encoding,
            attempt_sep,
            engine,
            best_cols,
        )
        if best_cols == 1:
            log.warning(
                "Only 1 column detected in %s — file may be wrong delimiter. "
                "Try: --csv-sep ,",
                path.name,
            )
        return best_df

    msg = (
        f"Could not parse CSV: {path}. "
        "Common causes: wrong delimiter, extra unquoted separators in fields, or mixed encodings. "
        f"Try --csv-sep , or --csv-sep {DEFAULT_CSV_SEP!r}."
    )
    if last_error:
        msg += f" Last error: {last_error}"
    raise ValueError(msg) from last_error


def _read_table(path: Path, *, csv_sep: str = DEFAULT_CSV_SEP) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return _normalize_dataframe_columns(pd.read_excel(path, dtype=str))
    if suffix == ".csv":
        return _read_csv(path, sep=csv_sep)
    raise ValueError(f"Unsupported input format: {path}")


def _collect_input_paths(path: Path) -> list[Path]:
    """Return one file path, or all supported files in a directory."""
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
            raise ValueError(
                f"Unsupported input format: {path}. "
                f"Supported: {', '.join(sorted(SUPPORTED_INPUT_SUFFIXES))}"
            )
        return [path]
    if path.is_dir():
        files = sorted(
            p
            for p in path.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
        )
        if not files:
            raise ValueError(
                f"No supported files in directory: {path}. "
                f"Supported: {', '.join(sorted(SUPPORTED_INPUT_SUFFIXES))}"
            )
        return files
    raise FileNotFoundError(f"Input not found: {path}")


def _enriched_output_root() -> Path:
    """``enriched/`` at the current working directory (project root when run from there)."""
    return Path.cwd() / ENRICHED_OUTPUT_DIR


def _resolve_output_path(
    inp: Path,
    output_root: Path,
    explicit_output: Path | None,
) -> Path:
    """Place output under ``<cwd>/enriched/`` using the same base name as the input."""
    if explicit_output is not None:
        return explicit_output
    return output_root / inp.name


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich dealer Excel/CSV with website provider, phone, email, "
            "chat widget, 360° vehicle viewer, customer AI, and dealer type"
        ),
    )
    parser.add_argument(
        "input",
        help="Excel (.xlsx) or CSV file, or a directory of those files",
    )
    parser.add_argument(
        "-o",
        "--output",
        help=(
            f"Output path (single input only). "
            f"Default: ./{ENRICHED_OUTPUT_DIR}/<input><ext> (same name as input)"
        ),
    )
    parser.add_argument(
        "--website-col",
        help="Column name for dealer website URLs (auto-detected if omitted)",
    )
    parser.add_argument(
        "--name-col",
        help="Column name for dealer / dealership name (auto-detected if omitted)",
    )
    parser.add_argument(
        "--state-col",
        help="Column name for US state (auto-detected if omitted; used to split -w/-W)",
    )
    parser.add_argument(
        "-W",
        "--total-workers",
        type=int,
        default=1,
        metavar="N",
        help="Total parallel terminal runs sharing the job (default: 1)",
    )
    parser.add_argument(
        "-w",
        "--worker",
        type=int,
        default=0,
        metavar="I",
        help="This run's worker index, 0 to N-1 (default: 0). Use with -W",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=6,
        help="HTTP fetch threads inside this process (default: 6)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="Fetch timeout per site in seconds (default: 45)",
    )
    parser.add_argument(
        "--fetch-mode",
        choices=("auto", "http", "browser"),
        default="auto",
        help=(
            "How to load dealer sites: auto=HTTP then browser if blocked (default), "
            "http=fast curl_cffi only, browser=Playwright Chromium"
        ),
    )
    parser.add_argument(
        "--browser-headed",
        action="store_true",
        help="Show browser window when using Playwright (helps with some CAPTCHAs)",
    )
    parser.add_argument(
        "--deep-detection",
        action="store_true",
        help=(
            "Broaden chat/AI/360 detection: capture browser-loaded integrations "
            "and sample vehicle-detail pages (slower; use -t 1 or -t 2)"
        ),
    )
    parser.add_argument(
        "--vdp-sample-size",
        type=int,
        default=3,
        metavar="N",
        help="Vehicle-detail pages to sample with --deep-detection (default: 3)",
    )
    parser.add_argument(
        "--csv-sep",
        default=DEFAULT_CSV_SEP,
        help=f"Column separator for .csv inputs (default: {DEFAULT_CSV_SEP!r})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        _validate_worker_args(args.worker, args.total_workers)
        if args.vdp_sample_size < 0:
            raise ValueError("--vdp-sample-size must be >= 0")
    except ValueError as exc:
        log.error("%s", exc)
        sys.exit(1)

    input_path = Path(args.input)
    try:
        all_inputs = _collect_input_paths(input_path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        sys.exit(1)

    if args.total_workers > 1:
        log.info("Distributed worker %s of %s", args.worker + 1, args.total_workers)

    single_file = len(all_inputs) == 1
    if single_file:
        inputs = all_inputs
        shard_rows = args.total_workers > 1
    else:
        inputs = _shard_input_paths(all_inputs, args.worker, args.total_workers)
        shard_rows = False
        if args.total_workers > 1 and not inputs:
            log.info(
                "Worker %s/%s: no input files assigned (of %s files)",
                args.worker + 1,
                args.total_workers,
                len(all_inputs),
            )
            return

    if len(all_inputs) > 1 and args.output:
        log.error("--output is only valid with a single input file")
        sys.exit(1)
    if args.output and args.total_workers > 1:
        log.error("--output cannot be used with -W > 1 (each worker writes its own file)")
        sys.exit(1)

    output_root = _enriched_output_root()
    explicit_out = Path(args.output) if args.output and single_file else None
    for inp in inputs:
        out = _resolve_output_path(inp, output_root, explicit_out)
        try:
            enrich_file(
                inp,
                out,
                website_col=args.website_col,
                name_col=args.name_col,
                state_col=args.state_col,
                threads=args.threads,
                timeout=args.timeout,
                csv_sep=args.csv_sep,
                worker=args.worker,
                total_workers=args.total_workers,
                shard_rows=shard_rows,
                fetch_mode=args.fetch_mode,
                headed=args.browser_headed,
                deep_detection=args.deep_detection,
                vdp_sample_size=args.vdp_sample_size,
            )
        except Exception as exc:
            log.error("%s: %s", inp, exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
