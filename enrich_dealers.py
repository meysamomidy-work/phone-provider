#!/usr/bin/env python3
"""
Enrich dealership Excel/CSV files with website provider, phone, email, chat widget,
and dealer type (franchise vs private) from dealer sites and names.

Every input row is written to the enriched output.
Failed website lookups include a note in Website Enrichment Notes explaining why.

Split work across terminals with -W (total workers) and -w (this worker, 0..N-1).
Multiple input files are split by file; a single file is split by state column or by row.
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

from dealer_chat_widget import detect_chat_widgets
from dealer_email import extract_primary_email
from dealer_phone import extract_primary_phone
from dealer_platforms import DEALER_PLATFORMS
from dealer_type import classify_dealer_type
from dealer_fetch import FetchMode, fetch_dealer_html, normalize_dealer_url
from website_provider import detect_from_html

log = logging.getLogger("enrich_dealers")

WEBSITE_COLUMN_CANDIDATES = (
    "website",
    "dealer website",
    "dealerwebsite",
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
OUTPUT_DEALER_TYPE_COL = "Dealer Type"
OUTPUT_NOTES_COL = "Website Enrichment Notes"

ENRICHMENT_COLS = (
    OUTPUT_PROVIDER_COL,
    OUTPUT_PHONE_COL,
    OUTPUT_EMAIL_COL,
    OUTPUT_CHAT_WIDGET_COL,
    OUTPUT_DEALER_TYPE_COL,
    OUTPUT_NOTES_COL,
)

REASON_NO_WEBSITE = "No dealer website provided"
REASON_SITE_NOT_LOADED = "Website could not be loaded"
REASON_PROVIDER_NOT_FOUND = "Website provider not detected on site"
REASON_PHONE_NOT_FOUND = "Phone number not found on website"
REASON_EMAIL_NOT_FOUND = "Email address not found on website"

SUPPORTED_INPUT_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls", ".csv"})
DEFAULT_CSV_SEP = "|"
ENRICHED_OUTPUT_DIR = "enriched_v2"


def _find_state_column(df: pd.DataFrame, override: str | None) -> str | None:
    if override:
        if override not in df.columns:
            raise ValueError(f"Column not found: {override!r}. Available: {list(df.columns)}")
        return override
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for key in STATE_COLUMN_CANDIDATES:
        if key in lower_map:
            return lower_map[key]
    for col in df.columns:
        if "state" in str(col).lower():
            return col
    return None


def _find_name_column(df: pd.DataFrame, override: str | None) -> str | None:
    if override:
        if override not in df.columns:
            raise ValueError(f"Column not found: {override!r}. Available: {list(df.columns)}")
        return override
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


def _find_column_case_insensitive(df: pd.DataFrame, target: str) -> str | None:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    return lower_map.get(target.strip().lower())


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
    if "enrichment notes" in low:
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
    dealer_type: str = "",
    has_website: bool = True,
    loaded: bool = True,
) -> dict[str, str]:
    return {
        OUTPUT_PROVIDER_COL: provider,
        OUTPUT_PHONE_COL: phone,
        OUTPUT_EMAIL_COL: email,
        OUTPUT_CHAT_WIDGET_COL: chat_widget,
        OUTPUT_DEALER_TYPE_COL: dealer_type,
        OUTPUT_NOTES_COL: _enrichment_notes(
            has_website=has_website,
            loaded=loaded,
            provider=provider,
            phone=phone,
            email=email,
        ),
    }


def _dealer_type_for_row(df: pd.DataFrame, idx: int, name_col: str | None) -> str:
    if not name_col:
        return ""
    val = df.at[idx, name_col]
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return classify_dealer_type(str(val))


def _existing_enrichment_for_row(
    df: pd.DataFrame,
    idx: int,
    *,
    notes_col: str | None,
    dealer_type: str,
) -> dict[str, str]:
    def get_if_exists(col: str) -> str:
        if col not in df.columns:
            return ""
        val = df.at[idx, col]
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        return str(val)

    notes = get_if_exists(notes_col) if notes_col else ""
    return {
        OUTPUT_PROVIDER_COL: get_if_exists(OUTPUT_PROVIDER_COL),
        OUTPUT_PHONE_COL: get_if_exists(OUTPUT_PHONE_COL),
        OUTPUT_EMAIL_COL: get_if_exists(OUTPUT_EMAIL_COL),
        OUTPUT_CHAT_WIDGET_COL: get_if_exists(OUTPUT_CHAT_WIDGET_COL),
        OUTPUT_DEALER_TYPE_COL: dealer_type or get_if_exists(OUTPUT_DEALER_TYPE_COL),
        OUTPUT_NOTES_COL: notes,
    }


def _should_retry_site_not_loaded(
    df: pd.DataFrame,
    idx: int,
    *,
    notes_col: str | None,
) -> bool:
    if not notes_col:
        return False
    raw = df.at[idx, notes_col]
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    note = str(raw).strip().lower()
    return note == REASON_SITE_NOT_LOADED.lower()


def _process_row(
    website: str,
    *,
    timeout: float,
    fetch_mode: str,
    headed: bool,
) -> tuple[dict[str, str], bool]:
    """Fetch dealer site; return (enrichment fields, site_loaded)."""
    base = normalize_dealer_url(str(website) if website is not None else "")
    if not base:
        return _make_enrichment(has_website=False, loaded=False), False

    fetched = fetch_dealer_html(
        base,
        timeout=timeout,
        mode=fetch_mode,
        headed=headed,
    )
    if not fetched:
        log.debug("site not loaded: %s", base)
        return _make_enrichment(loaded=False), False

    final_url, html = fetched
    provider_match = detect_from_html(html, source_url=final_url)
    provider_name = ""
    if provider_match and provider_match.display_name in DEALER_PLATFORMS:
        provider_name = provider_match.display_name

    phone = extract_primary_phone(html) or ""
    email = extract_primary_email(html) or ""
    chat_widget = detect_chat_widgets(html)

    return (
        _make_enrichment(
            provider=provider_name,
            phone=phone,
            email=email,
            chat_widget=chat_widget,
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
) -> None:
    if fetch_mode in (FetchMode.BROWSER.value, FetchMode.AUTO.value) and threads > 2:
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
    notes_column = _find_column_case_insensitive(df, OUTPUT_NOTES_COL)
    has_any_enrichment_cols = any(c in df.columns for c in ENRICHMENT_COLS)
    retry_site_not_loaded_only = notes_column is not None
    log.info("Input %s: %s rows, website column %r", input_path.name, len(df), col)
    if name_column:
        log.info("Dealer type from name column %r", name_column)
    else:
        log.warning("No dealer name column found; Dealer Type will be empty (use --name-col)")
    if retry_site_not_loaded_only:
        log.info(
            "Detected existing enrichment notes; retrying only rows with %r via browser fetch",
            REASON_SITE_NOT_LOADED,
        )

    if df.empty:
        log.warning("No rows in %s", input_path.name)

    enrichments: dict[int, dict[str, str]] = {}
    rows_with_url: list[tuple[int, str, str]] = []
    no_website = 0
    skipped_existing = 0

    for idx, val in df[col].items():
        dealer_type = _dealer_type_for_row(df, idx, name_column)
        url = normalize_dealer_url(str(val) if pd.notna(val) else "")
        if not url:
            if has_any_enrichment_cols:
                enrichments[idx] = _existing_enrichment_for_row(
                    df,
                    idx,
                    notes_col=notes_column,
                    dealer_type=dealer_type,
                )
                skipped_existing += 1
            else:
                enrichments[idx] = _make_enrichment(
                    has_website=False,
                    loaded=False,
                    dealer_type=dealer_type,
                )
                no_website += 1
            continue

        if retry_site_not_loaded_only:
            if _should_retry_site_not_loaded(df, idx, notes_col=notes_column):
                rows_with_url.append((idx, str(val), FetchMode.BROWSER.value))
            else:
                enrichments[idx] = _existing_enrichment_for_row(
                    df,
                    idx,
                    notes_col=notes_column,
                    dealer_type=dealer_type,
                )
                skipped_existing += 1
            continue

        rows_with_url.append((idx, str(val), fetch_mode))

    def task(item: tuple[int, str, str]) -> tuple[int, dict[str, str], bool]:
        idx, url, row_fetch_mode = item
        enrichment, loaded = _process_row(
            url,
            timeout=timeout,
            fetch_mode=row_fetch_mode,
            headed=headed,
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
                _make_enrichment(has_website=False, loaded=False),
            )
            row_enrichment[OUTPUT_DEALER_TYPE_COL] = _dealer_type_for_row(
                df, idx, name_column
            )
            writer.append(_build_output_row(df, idx, row_enrichment))
    finally:
        writer.close()

    log.info(
        "Wrote %s (%s rows: %s no website, %s retried site-not-loaded, %s kept existing, %s still not loaded)",
        output_path,
        writer.count,
        no_website,
        len(rows_with_url),
        skipped_existing,
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
    """Place output under ``<cwd>/enriched/`` using the same base name as the input."""
    if explicit_output is not None:
        return explicit_output
    return output_root / inp.name


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich dealer Excel/CSV with website provider, phone, email, "
            "chat widget, and dealer type"
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
            )
        except Exception as exc:
            log.error("%s: %s", inp, exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
