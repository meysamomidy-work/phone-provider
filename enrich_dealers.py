#!/usr/bin/env python3
"""
Enrich dealership Excel files with website provider and phone from dealer sites.

Each successfully enriched dealership is appended to the output file immediately.
Rows whose website cannot be fetched are dropped.
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
from website_provider import (
    TARGET_PROVIDER_NAMES,
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
OUTPUT_FETCHED_URL_COL = "Website Fetched URL"

ENRICHMENT_COLS = (OUTPUT_PROVIDER_COL, OUTPUT_PHONE_COL, OUTPUT_FETCHED_URL_COL)

SUPPORTED_INPUT_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls", ".csv"})


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


def _process_row(website: str, *, timeout: float) -> dict[str, Any] | None:
    """Fetch dealer site; return enrichment fields or None to drop the row."""
    base = normalize_dealer_url(str(website) if website is not None else "")
    if not base:
        return None

    fetched = fetch_dealer_html(base, timeout=timeout)
    if not fetched:
        log.debug("drop (fetch failed): %s", base)
        return None

    final_url, html = fetched
    provider_match = detect_from_html(html, source_url=final_url)
    provider_name = ""
    if provider_match and provider_match.display_name in TARGET_PROVIDER_NAMES:
        provider_name = provider_match.display_name

    phone = extract_primary_phone(html) or ""

    return {
        OUTPUT_PROVIDER_COL: provider_name,
        OUTPUT_PHONE_COL: phone,
        OUTPUT_FETCHED_URL_COL: final_url,
    }


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
) -> None:
    df = _read_table(input_path)
    col = _find_website_column(df, website_col)
    log.info("Input %s: %s rows, website column %r", input_path.name, len(df), col)

    rows_with_url: list[tuple[int, str]] = []
    for idx, val in df[col].items():
        if normalize_dealer_url(str(val) if pd.notna(val) else ""):
            rows_with_url.append((idx, str(val)))

    if not rows_with_url:
        log.warning("No rows with a usable website URL")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_columns = _output_columns(df)
    writer = IncrementalWriter(output_path, out_columns)

    dropped = 0

    def task(item: tuple[int, str]) -> tuple[int, dict[str, Any] | None]:
        idx, url = item
        return idx, _process_row(url, timeout=timeout)

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(task, item): item[0] for item in rows_with_url}
            for fut in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="Dealer websites",
                unit="site",
            ):
                idx, result = fut.result()
                if result is None:
                    dropped += 1
                    continue
                writer.append(_build_output_row(df, idx, result))
    finally:
        writer.close()

    log.info(
        "Wrote %s line by line (%s rows kept, %s dropped: site not loaded)",
        output_path,
        writer.count,
        dropped,
    )


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, dtype=str)
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str)
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
        help="Output path (single input only). Default: <input>_enriched<ext>",
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

    for inp in inputs:
        if args.output and len(inputs) == 1:
            out = Path(args.output)
        else:
            out = inp.with_name(f"{inp.stem}_enriched{inp.suffix}")
        try:
            enrich_file(
                inp,
                out,
                website_col=args.website_col,
                workers=args.workers,
                timeout=args.timeout,
            )
        except Exception as exc:
            log.error("%s: %s", inp, exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
