#!/usr/bin/env python3
"""
Test dealer site fetching (HTTP vs browser) on URLs that previously hit CAPTCHA.

Examples:
    python test_fetch.py https://www.example-dealer.com
    python test_fetch.py https://www.example-dealer.com --mode browser --headed
    python test_fetch.py https://www.example-dealer.com --compare
    python test_fetch.py https://www.example-dealer.com --save-html out.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dealer_fetch import (
    FetchMode,
    fetch_dealer_html,
    fetch_dealer_html_with_meta,
    fetch_http,
    is_challenge_page,
    normalize_dealer_url,
)


def _run_one(label: str, url: str, *, mode: str, timeout: float, headed: bool) -> dict:
    print(f"\n--- {label} (mode={mode}) ---")
    meta = fetch_dealer_html_with_meta(url, mode=mode, timeout=timeout, headed=headed)
    print(json.dumps(meta, indent=2))
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Test dealer website fetching against CAPTCHA/Cloudflare")
    parser.add_argument("url", help="Dealer website URL that previously failed to load")
    parser.add_argument(
        "--mode",
        choices=("auto", "http", "browser", "compare"),
        default="compare",
        help="Fetch mode (default: compare http then auto/browser)",
    )
    parser.add_argument("--timeout", type=float, default=45.0, help="Timeout per attempt in seconds")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (browser mode only; often helps with CAPTCHA)",
    )
    parser.add_argument(
        "--save-html",
        metavar="FILE",
        help="Save successful HTML to this file",
    )
    args = parser.parse_args()

    base = normalize_dealer_url(args.url)
    if not base:
        print(f"Invalid URL: {args.url!r}", file=sys.stderr)
        sys.exit(1)

    print(f"Testing: {base}")

    results: list[dict] = []

    if args.mode == "compare":
        # Old-style HTTP only
        http_only = fetch_http(base, timeout=args.timeout)
        if http_only:
            final_url, html, method = http_only
            meta = {
                "label": "http_only",
                "success": True,
                "final_url": final_url,
                "html_bytes": len(html),
                "method": method,
                "challenge": is_challenge_page(html),
            }
        else:
            meta = {"label": "http_only", "success": False, "error": "failed or challenge"}
        print("\n--- http only (curl_cffi session) ---")
        print(json.dumps(meta, indent=2))
        results.append(meta)

        results.append(_run_one("auto (http then browser)", base, mode="auto", timeout=args.timeout, headed=args.headed))
        results.append(
            _run_one("browser only", base, mode="browser", timeout=args.timeout, headed=args.headed)
        )
    else:
        results.append(_run_one(args.mode, base, mode=args.mode, timeout=args.timeout, headed=args.headed))

    best = next((r for r in reversed(results) if r.get("success")), None)
    if best and args.save_html:
        fetched = fetch_dealer_html(
            base,
            timeout=args.timeout,
            mode=FetchMode(args.mode if args.mode != "compare" else "auto"),
            headed=args.headed,
        )
        if fetched:
            _, html = fetched
            path = Path(args.save_html)
            path.write_text(html, encoding="utf-8")
            print(f"\nSaved {len(html)} bytes to {path.resolve()}")

    if best and best.get("success") and not best.get("challenge"):
        print("\nPASS: Usable HTML retrieved.")
        sys.exit(0)

    print(
        "\nFAIL: Still blocked or empty. Try: --mode browser --headed "
        "(visible browser often clears Cloudflare).",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
