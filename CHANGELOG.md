# Changelog

## Version 1 (1.0.0) — 2026-11-25

First working release.

### Scraper
- Fetches everything with `requests` only. There is no JSON API, so the site's HTML is
  parsed (see `docs/SITE_STUDY.md`).
- Crawls every listing for rent and sale. It runs one search per (purpose, property type),
  plus the broad search, and removes duplicates by code and purpose.
- Fetches each listing's detail page: type, price, condo fee, IPTU, area, bedrooms, suites,
  bathrooms, parking, neighbourhood, city, amenities, description and every photo URL.
- Updates `data/listings.json` incrementally:
  - `first_seen`, `last_seen`, `updated_at` and `removed_at`
  - status: `active`, `unlisted` or `removed`
  - price history
  - a change report per run in `data/runs/`
- Optionally downloads photos to `data/images/`, fetching only the ones not already on disk.
- Safety check: refuses to mark listings as removed when a run finds less than half of the
  previous listings.
- A crawl limited with `--purpose` only touches listings of that purpose.
- CLI commands: `crawl`, `view`, `get`, `search`, `types`, `neighborhoods`.
- Selenium network-study tool in `tools/network_study.py`.

### Slideshow viewer
- `viewer/index.html` shows 1, 2 or 3 houses at a time. Photos are fitted to the screen and
  never cropped.
- Settings menu: time between slides, houses at a time, photos per house, rent/sale filter,
  order, and which parts of the overlay to show.
- Opens automatically after a crawl run from a terminal. Runs without a terminal (cron)
  skip it.
