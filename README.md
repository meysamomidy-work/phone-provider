# Dealer website enrichment

`enrich_dealers.py` fetches each dealer site and adds website-provider, phone,
email, chat, dealer-type, 360° viewer, and customer-AI fields.

```powershell
python enrich_dealers.py ..\google-maps\enriched_new -t 6 --fetch-mode auto
```

## Run on a fresh Linux VM with Docker

Install Docker Engine with the Compose plugin, copy this `phone-provider` folder
to the VM, and put the input CSV/XLSX inside it (for example,
`enriched_v8/Louisiana.csv`). From the `phone-provider` directory, run one
command:

```bash
docker compose run --build --rm --user "$(id -u):$(id -g)" dealer-enrichment \
  /input/enriched_v8/Louisiana.csv --staff-emails-only -t 2 --fetch-mode auto
```

This builds the image on first use, including Python dependencies and Chromium.
The source folder is mounted read-only at `/input`; outputs are written to the
host's `docker-output/` folder. For this example, the result is
`docker-output/enriched_v9/Louisiana.csv`. Change the `/input/...` path and
script flags in the same command for another file or mode. The UID/GID option
keeps output files owned by the Linux user who ran Docker. Browser runs are
headless in the container; do not pass `--browser-headed` without adding a
display server. Docker does not bypass site CAPTCHA or IP restrictions.

## Staff-email-only enrichment

To extend an existing dealer file with public contact/staff emails without
running the other enrichers, use `--staff-emails-only`. The source file is
never edited: a versioned `enriched_vN/` input writes to `enriched_v(N+1)/`
by default (or to `-o` for one file). All unrelated source columns are retained.
The pass writes `Staff Emails`, `Staff Email Scan Status`,
`Staff Email Scan Notes`, `Staff Email Scan Pages`, and `Staff Email Types`.

```powershell
python enrich_dealers.py ..\google-maps\enriched_new\dealers.csv `
  --staff-emails-only -t 2 --fetch-mode auto
```

The worker launcher supports the same focused pass. Its fifth positional
argument selects `deep` (default), `standard`, `staff`, or `staff-refresh`;
the optional sixth argument sets the staff-page limit:

```bat
run_workers.bat dealers.csv 6 2 0 staff 8
run_workers.bat enriched_v8\Louisiana.csv 1 2 0 staff-refresh 8
```

`Staff Emails` is compact JSON so CSV and Excel consumers retain the person
context together, for example:

```json
[{"email":"jordan@dealer.com","name":"Jordan Lee","role":"General Manager"}]
```

`Staff Email Types` is a separate JSON map from address to `person`,
`department`, `general`, or `unidentified`. The last category means the
address is public but its owner could not be verified; it is not assumed to
belong to a staff member. The `Staff Emails` JSON does not contain a source URL.

The pass scans the homepage, then follows up to eight same-site links ranked
as contact, staff, team, leadership, management, people, or directory pages.
It extracts normal `mailto:` links, visible text, structured JSON-LD, common
`[at]`/`[dot]` obfuscation, and Cloudflare's public email obfuscation. Set
`--staff-page-limit N` to tune that bounded scan. The default rerun retries
empty rows and cleans invalid addresses/misleading metadata in populated
rows, without discarding valid prior addresses. Add `--staff-refresh-generic`
to revisit populated rows that have no named contact and merge any new
findings with their valid existing emails. `staff-refresh` in the worker
launcher selects that mode. Rows with named contacts remain skipped.
When normal links and common staff paths do not yield a named staff address,
the crawler checks a bounded same-site sitemap and follows profile links from
staff listings. A failed homepage also gets two HTTP-only hostname/scheme
variants. Candidate HTML pages remain within the staff-page limit, and sitemap
attempts are recorded in the scan diagnostics. Sitemap requests and homepage
retries have their own small fixed bounds.

The scan diagnostics distinguish fetch failures, contact forms, named staff
without public email, and empty listings. A staff page that lists people but
publishes no email cannot yield a verified staff address; the crawler does not
guess one from a person's name or the dealership domain.

For a broader pass over integrations that are injected by JavaScript or only
exist on a vehicle-detail page, use deep detection. It opens a browser for the
home page, captures loaded script/frame/API URLs, and samples up to three
likely vehicle pages. It is materially slower, so keep threads at one or two.

```powershell
python enrich_dealers.py discovered -t 2 --fetch-mode auto `
  --deep-detection --vdp-sample-size 3
```

This is an evidence-based detector, not a complete vendor catalogue: named
providers are reported when their actual embed/delivery signature is found;
unknown but clearly implemented widgets are reported as a conservative
generic result. Existing populated enrichment cells are never overwritten,
including when deep detection is enabled.

The two new fields are deliberately separate:

- `360° Vehicle Viewer` identifies embedded spin/turntable integrations (for
  example, Impel / SpinCar), or a conservative `Generic 360° viewer` result.
- `Customer AI` identifies a known customer-facing AI assistant or explicitly
  AI-powered chat. `Chat Widget` continues to include both live-chat and AI
  providers, so it should not by itself be read as an AI result.

## Filling missing dealer websites

After the Google Maps stage, run `discover_websites.py` before enrichment. It
checks Google Places first, then Exa Search, Tavily Search, Google Custom
Search (when configured), and finally the independent Brave Search API. Search
fallbacks inspect only the first three results and require a matching dealer
page before accepting a site. No source overwrites the original `Website` or
`Google Map Website` columns. It produces `Resolved Website`, which
`enrich_dealers.py` now chooses first.

Social-media, directory, and search-provider profile URLs are rejected. If a
candidate site presents a CAPTCHA, it can be accepted only when its title and
domain strongly match the dealership (at least 90/100 confidence).

```powershell
python discover_websites.py ..\google-maps\enriched_new `
  -o discovered `
  --google-places-api-key YOUR_GOOGLE_PLACES_KEY `
  --exa-api-key YOUR_EXA_KEY `
  --tavily-api-key YOUR_TAVILY_KEY `
  --google-custom-search-api-key YOUR_GOOGLE_CUSTOM_SEARCH_KEY `
  --google-custom-search-cx YOUR_PROGRAMMABLE_SEARCH_ENGINE_ID `
  --brave-search-api-key YOUR_BRAVE_SEARCH_KEY

python enrich_dealers.py discovered -t 6 --fetch-mode auto
```

Enable the Places API (New) for the Google Cloud project used by the key.
Google Custom Search is available only to existing Custom Search JSON API
customers. Tavily is the recommended web-search fallback for new accounts.
Exa and Tavily are the recommended web-search fallbacks for new accounts. The
Brave key is optional and is only used when earlier providers return no verified
candidate. A candidate is only accepted when it reaches confidence 75/100; use
`--min-confidence 85` for a stricter list. Rows still missing a site retain an
explanation in `Website Discovery Notes`, which makes them suitable for manual
review or a second search provider later.
