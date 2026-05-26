#!/usr/bin/env python3
"""
Enrich dealership Excel files with website provider and phone from dealer sites.

Every input row is written to the enriched output.
Failed provider/phone lookups include a note in Website Enrichment Notes explaining why.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from tqdm import tqdm

from dealer_phone import extract_primary_phone
from dealer_platforms import DEALER_PLATFORMS
from website_provider import (
    detect_from_html,
    fetch_dealer_html,
    normalize_dealer_url,
)

log = logging.getLogger("enrich_dealers")

WEBSITE_COLUMN_CANDIDATES = (
    "website",
    "dealer website",
    "dealerwebsite",
    "url",
    "web site",
    "site",
)

OUTPUT_PROVIDER_COL = "Website Provider"
OUTPUT_PHONE_COL = "Website Phone"
OUTPUT_NOTES_COL = "Website Enrichment Notes"

ENRICHMENT_COLS = (OUTPUT_PROVIDER_COL, OUTPUT_PHONE_COL, OUTPUT_NOTES_COL)

REASON_NO_WEBSITE = "No dealer website provided"
REASON_SITE_NOT_LOADED = "Website could not be loaded"
REASON_PROVIDER_NOT_FOUND = "Website provider not detected on site"
REASON_PHONE_NOT_FOUND = "Phone number not found on website"

SUPPORTED_INPUT_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls", ".csv"})
DEFAULT_CSV_SEP = "|"
ENRICHED_OUTPUT_DIR = "enriched"


def _find_website_column(df: pd.DataFrame, override: str | None) -> str:
    if override:
        if override not in df.columns:
            raise ValueError(f"Column not found: {override!r}. Available: {list(df.columns)}")
        return override
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for key in WEBSITE_COLUMN_CANDIDATES:
        if key in lower_map:
            return lower_map[key]
    for col in df.columns:
        if "website" in str(col).lower():
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


def _output_columns(df: pd.DataFrame) -> list[str]:
    cols = list(df.columns)
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
) -> str:
    """Human-readable reasons when provider and/or phone could not be enriched."""
    if not has_website:
        return REASON_NO_WEBSITE
    if not loaded:
        return REASON_SITE_NOT_LOADED

    reasons: list[str] = []
    if not provider:
        reasons.append(REASON_PROVIDER_NOT_FOUND)
    if not phone:
        reasons.append(REASON_PHONE_NOT_FOUND)
    return "; ".join(reasons)


def _make_enrichment(
    *,
    provider: str = "",
    phone: str = "",
    has_website: bool = True,
    loaded: bool = True,
) -> dict[str, str]:
    return {
        OUTPUT_PROVIDER_COL: provider,
        OUTPUT_PHONE_COL: phone,
        OUTPUT_NOTES_COL: _enrichment_notes(
            has_website=has_website,
            loaded=loaded,
            provider=provider,
            phone=phone,
        ),
    }


def _process_row(website: str, *, timeout: float) -> tuple[dict[str, str], bool]:
    """Fetch dealer site; return (enrichment fields, site_loaded)."""
    base = normalize_dealer_url(str(website) if website is not None else "")
    if not base:
        return _make_enrichment(has_website=False, loaded=False), False

    fetched = fetch_dealer_html(base, timeout=timeout)
    if not fetched:
        log.debug("site not loaded: %s", base)
        return _make_enrichment(loaded=False), False

    final_url, html = fetched
    provider_match = detect_from_html(html, source_url=final_url)
    provider_name = ""
    if provider_match and provider_match.display_name in DEALER_PLATFORMS:
        provider_name = provider_match.display_name

    phone = extract_primary_phone(html) or ""

    return _make_enrichment(provider=provider_name, phone=phone, loaded=True), True


def _build_output_row(df: pd.DataFrame, idx: int, enrichment: dict[str, Any]) -> dict[str, Any]:
    row = {col: df.at[idx, col] for col in df.columns}
    row.update(enrichment)
    return row


def enrich_file(
    input_path: Path,
    output_path: Path,
    *,
    website_col: str | None,
    workers: int,
    timeout: float,
    csv_sep: str = DEFAULT_CSV_SEP,
) -> None:
    df = _read_table(input_path, csv_sep=csv_sep)
    col = _find_website_column(df, website_col)
    log.info("Input %s: %s rows, website column %r", input_path.name, len(df), col)

    if df.empty:
        log.warning("No rows in %s", input_path.name)

    enrichments: dict[int, dict[str, str]] = {}
    rows_with_url: list[tuple[int, str]] = []
    no_website = 0

    for idx, val in df[col].items():
        url = normalize_dealer_url(str(val) if pd.notna(val) else "")
        if url:
            rows_with_url.append((idx, str(val)))
        else:
            enrichments[idx] = _make_enrichment(has_website=False, loaded=False)
            no_website += 1

    def task(item: tuple[int, str]) -> tuple[int, dict[str, str], bool]:
        idx, url = item
        enrichment, loaded = _process_row(url, timeout=timeout)
        return idx, enrichment, loaded

    unloaded = 0
    if rows_with_url:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
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
                _make_enrichment(has_website=False, loaded=False),
            )
            writer.append(_build_output_row(df, idx, row_enrichment))
    finally:
        writer.close()

    log.info(
        "Wrote %s (%s rows: %s no website, %s site not loaded)",
        output_path,
        writer.count,
        no_website,
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
    """Read pipe-delimited (or other) dealer CSV exports."""
    last_error: Exception | None = None

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        attempts: list[tuple[str, str, str | None]] = [
            (sep, "c", None),
            (_sniff_csv_delimiter(path, encoding=encoding), "python", "warn"),
            (",", "python", "warn"),
            (";", "python", "warn"),
            ("\t", "python", "warn"),
        ]
        seen: set[tuple[str, str, str | None]] = set()
        for sep, engine, on_bad_lines in attempts:
            key = (sep, engine, on_bad_lines)
            if key in seen:
                continue
            seen.add(key)

            kwargs: dict[str, Any] = {
                "filepath_or_buffer": path,
                "dtype": str,
                "encoding": encoding,
                "sep": sep,
                "engine": engine,
            }
            if on_bad_lines is not None:
                kwargs["on_bad_lines"] = on_bad_lines

            try:
                df = pd.read_csv(**kwargs)
                if sep != DEFAULT_CSV_SEP or engine != "c":
                    log.info(
                        "Parsed %s with encoding=%s, sep=%r, engine=%s",
                        path.name,
                        encoding,
                        sep,
                        engine,
                    )
                return df
            except UnicodeDecodeError as exc:
                last_error = exc
                break
            except pd.errors.ParserError as exc:
                last_error = exc
                log.debug(
                    "CSV parse failed for %s (encoding=%s, sep=%r, engine=%s): %s",
                    path.name,
                    encoding,
                    sep,
                    engine,
                    exc,
                )
                continue

    msg = (
        f"Could not parse CSV: {path}. "
        "Common causes: wrong delimiter, extra unquoted separators in fields, or mixed encodings. "
        f"Dealer files are expected to use {DEFAULT_CSV_SEP!r} by default; try --csv-sep if needed."
    )
    if last_error:
        msg += f" Last error: {last_error}"
    raise ValueError(msg) from last_error


def _read_table(path: Path, *, csv_sep: str = DEFAULT_CSV_SEP) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, dtype=str)
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
    """Place enriched files under ``<cwd>/enriched/``, not beside the input file."""
    if explicit_output is not None:
        return explicit_output
    return output_root / f"{inp.stem}_enriched{inp.suffix}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich dealer Excel/CSV with website provider and phone from dealer sites",
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
            f"Default: ./{ENRICHED_OUTPUT_DIR}/<input>_enriched<ext>"
        ),
    )
    parser.add_argument(
        "--website-col",
        help="Column name for dealer website URLs (auto-detected if omitted)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Parallel fetch workers (default: 6)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout per request in seconds (default: 30)",
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

    input_path = Path(args.input)
    try:
        inputs = _collect_input_paths(input_path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        sys.exit(1)

    if len(inputs) > 1 and args.output:
        log.error("--output is only valid with a single input file")
        sys.exit(1)

    output_root = _enriched_output_root()
    explicit_out = Path(args.output) if args.output and len(inputs) == 1 else None
    for inp in inputs:
        out = _resolve_output_path(inp, output_root, explicit_out)
        try:
            enrich_file(
                inp,
                out,
                website_col=args.website_col,
                workers=args.workers,
                timeout=args.timeout,
                csv_sep=args.csv_sep,
            )
        except Exception as exc:
            log.error("%s: %s", inp, exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
