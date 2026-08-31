"""Collect possible 360-viewer signatures from Exa result exports.

Exa results are leads, not proof that a page embeds a vehicle viewer.  This
tool fetches each result and writes the small set of markup/resource URLs that
look relevant, so rules can be verified before they are added to the detector.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from dealer_360_imaging import detect_360_viewers
from dealer_fetch import extract_resource_urls, fetch_dealer_html

_INTERESTING = re.compile(r"(?:360|spin|viewer|walkaround|turntable|panorama|virtual[-_ ]?tour)", re.I)
_TAG = re.compile(
    r"<(?:iframe|script|canvas|model-viewer)[^>]*(?:360|spin|viewer|walkaround|turntable|panorama)[^>]*>",
    re.I,
)


def _urls(paths: list[Path]) -> list[str]:
    found: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        for result in payload.get("results", []):
            url = str(result.get("url") or "").strip()
            if url.startswith(("https://", "http://")):
                found.add(url)
    return sorted(found)


def _title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip()[:180] if match else ""


def _inspect(url: str, timeout: float) -> dict[str, object]:
    fetched = fetch_dealer_html(url, timeout=timeout, mode="http")
    if not fetched:
        return {"url": url, "success": False, "reason": "fetch failed or challenge"}

    final_url, html = fetched
    resources = sorted(resource for resource in extract_resource_urls(html, final_url) if _INTERESTING.search(resource))
    tags = _TAG.findall(html)
    return {
        "url": url,
        "final_url": final_url,
        "host": urlparse(final_url).netloc.lower(),
        "success": True,
        "title": _title(html),
        "html_bytes": len(html),
        "current_detection": detect_360_viewers(html),
        "viewer_tags": tags[:20],
        "interesting_resources": resources[:100],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Exa JSON result files")
    parser.add_argument("--output", type=Path, default=Path("360-candidate-evidence.json"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    urls = _urls(args.inputs)
    print(f"Inspecting {len(urls)} unique Exa URLs...")
    records: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        jobs = {pool.submit(_inspect, url, args.timeout): url for url in urls}
        for job in as_completed(jobs):
            record = job.result()
            records.append(record)
            print(f"{'OK' if record['success'] else 'SKIP'} {jobs[job]}")

    records.sort(key=lambda row: str(row["url"]))
    args.output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    successful = sum(bool(row["success"]) for row in records)
    evidence = sum(bool(row.get("viewer_tags") or row.get("interesting_resources")) for row in records)
    print(f"Saved {successful} fetched pages; {evidence} with possible viewer evidence -> {args.output}")


if __name__ == "__main__":
    main()
