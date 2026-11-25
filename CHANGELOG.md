# Changelog

Versions are created automatically by `.github/workflows/release.yml` on every push
(rules in `tools/next_version.py`). This file summarises what each one contains.

## Next release

### Slideshow
- White background throughout: the photo area, the details panel, the settings menu and the loader.
- Removed the coloured frame around each house. The ALUGUEL/VENDA tag in the top-right
  corner is now the only rent/sale marker.
- `←` / `→` now skip to the previous or next house(s), like `↑` / `↓`. No key steps through
  photos any more; they change on the "Tempo entre fotos" timer.

## v1.2.0 — 2026-11-24
- One-click Windows installer (`instalar.bat`). It downloads the latest release, installs Python
  if needed, creates the virtual environment, adds launchers and can schedule the daily crawl.

## v1.1.0 — 2026-11-24
- Separate timers: "Tempo entre fotos" (photo changes) and "Tempo entre imóveis" (house changes).

## v1.0.0 — 2026-11-24
First release: the working scraper and slideshow.

### Scraper
- Fetches everything with `requests` only. There is no JSON API, so the site's HTML is parsed
  (see `docs/SITE_STUDY.md`).
- Crawls every listing for rent and sale, with all details and photo URLs, into
  `data/listings.json`.
- Daily incremental updates: first and last seen, active/unlisted/removed status, price
  history, and a change report per run.
- Optional photo download (only new files), a safety check against mass removals, and
  `--purpose`-limited crawls.
- CLI commands: `crawl`, `view`, `get`, `search`, `types`, `neighborhoods`. The interface is
  in Brazilian Portuguese.

### Slideshow
- 1, 2 or 3 houses per screen, photo timer, photos per house, image fit options, filters,
  order, and toggles for the overlay.
- Opens automatically after an interactive crawl.
