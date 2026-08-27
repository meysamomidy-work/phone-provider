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
