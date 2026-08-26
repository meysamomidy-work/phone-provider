# Dealer website enrichment

`enrich_dealers.py` fetches each dealer site and adds website-provider, phone,
email, chat, dealer-type, 360° viewer, and customer-AI fields.

```powershell
python enrich_dealers.py ..\google-maps\enriched_new -t 6 --fetch-mode auto
```

The two new fields are deliberately separate:

- `360° Vehicle Viewer` identifies embedded spin/turntable integrations (for
  example, Impel / SpinCar), or a conservative `Generic 360° viewer` result.
- `Customer AI` identifies a known customer-facing AI assistant or explicitly
  AI-powered chat. `Chat Widget` continues to include both live-chat and AI
  providers, so it should not by itself be read as an AI result.

## Filling missing dealer websites

After the Google Maps stage, run `discover_websites.py` before enrichment. It
checks Google Places first and can use the independent Brave Search API for the
rows where Google has no official site. Both sources are checked against dealer
name plus ZIP/phone evidence, and neither overwrites the original `Website` or
`Google Map Website` columns. It produces `Resolved Website`, which
`enrich_dealers.py` now chooses first.

```powershell
python discover_websites.py ..\google-maps\enriched_new `
  -o discovered `
  --google-places-api-key YOUR_GOOGLE_PLACES_KEY `
  --brave-search-api-key YOUR_BRAVE_SEARCH_KEY

python enrich_dealers.py discovered -t 6 --fetch-mode auto
```

Enable the Places API (New) for the Google Cloud project used by the key. The
Brave key is optional but recommended because it is an independent web index;
it is only used when Places returns no verified candidate. A candidate is only
accepted when it reaches confidence 75/100; use
`--min-confidence 85` for a stricter list. Rows still missing a site retain an
explanation in `Website Discovery Notes`, which makes them suitable for manual
review or a second search provider later.
