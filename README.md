# rm-scraping

A scraper for **https://www.rmbhimoveis.com.br/** (RM Imóveis, Belo Horizonte) that uses only requests.
It collects every property currently listed for rent or sale, with all the data the site
publishes and every photo. The output is a structured JSON database that is updated in place
each time you run it, so it is meant to run once a day.

- No browser is needed at runtime: only `requests`, `beautifulsoup4` and `lxml`.
- Selenium was used only to study the site. The study tool is in `tools/network_study.py`
  and the findings are in [`docs/SITE_STUDY.md`](docs/SITE_STUDY.md).

## Install

### Windows: one file does everything

Download **[RM-Imoveis.bat](https://github.com/alexctrl/rm-scraping/releases/latest/download/RM-Imoveis.bat)**
into the folder where you want the program, then double-click it whenever you want to use it.

- **The first time** it installs into that folder:
  - downloads the latest release from GitHub;
  - installs Python 3.12 for your user if no Python 3.9+ is found (no admin rights needed);
  - creates `.venv\` and installs the dependencies;
  - optionally schedules a daily background crawl in the Windows Task Scheduler. The task is
    named `RM Imoveis - coleta diaria` and logs to `data\coleta.log`.
- **Every time**, including the first:
  1. It checks GitHub for a newer release. If there is one, it downloads it and updates itself;
     a newer copy of `RM-Imoveis.bat` takes effect from the next run.
  2. It crawls the site. If the crawl fails, the last data is shown.
  3. It opens the slideshow full screen in Chrome or Edge. `F11` leaves full screen, and closing
     the window (`Alt+F4`) ends the program.
- Without internet it skips the update and the crawl fails, so the slideshow shows the last data.
- Your `data\` folder is never touched. The slideshow's settings are kept in `data\.navegador\`.
- Windows may show a SmartScreen warning the first time, because the file was downloaded from
  the internet. Click *Mais informações → Executar assim mesmo*.

### Manually

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## Daily crawl

```bash
python -m rmbh_scraper crawl --images        # full crawl + download new photos, then open the slideshow
python -m rmbh_scraper crawl                 # data only (image URLs, no download), then open the slideshow
python -m rmbh_scraper view                  # just open the slideshow for the current data
```

When a crawl run from a terminal finishes, it starts a local web server and opens the
slideshow (`http://127.0.0.1:8000/viewer/`) in your browser. Press `Ctrl+C` to stop it.
- `--no-view` skips the slideshow.
- `--no-browser` starts the server without opening a browser.
- `--fullscreen` opens the slideshow full screen in Chrome or Edge, in its own window and profile.
  Closing that window stops the server.
- `--port N` uses a different port. If the port is busy, the next free one is used.
- Runs without a terminal (cron, CI) skip the viewer automatically and exit when the
  crawl is done.

Example cron line (runs every day at 06:15):

```cron
15 6 * * * cd /path/to/rm-scraping && .venv/bin/python -m rmbh_scraper crawl --images --no-view >> data/crawl.log 2>&1
```

Each run does the following:
1. Reads the property types for each purpose and runs one search per (purpose, type), plus
   the broad search (type 0). The results are de-duplicated.
2. Fetches every listing's detail page in parallel. The rate is limited per host:
   0.25 s for the site (`--delay`) and 0.05 s for the image CDN.
3. Merges the results into `data/listings.json`:
   - `status`: `active`, `unlisted` (missing from the searches but the page still exists) or `removed`
   - `first_seen`, `last_seen`, `updated_at` and `removed_at`
   - `price_history`: a new entry is added whenever the price changes
   - `content_hash`: used to detect changes in the tracked fields
4. Writes a change report to `data/runs/<timestamp>.json` with the codes that were added,
   changed (and which fields), removed or unlisted.
5. With `--images`, downloads only the photos that are not already on disk, to
   `data/images/<id>/NNN_<file>`.

**Safety check:** if a run finds fewer than 50% of the previously active listings (for
example because the site is down or its layout changed), it stops before writing anything.
Use `--force` to accept the run anyway.

## JSON structure (`data/listings.json`)

```jsonc
{
  "meta": {
    "schema_version": 1,
    "source": "https://www.rmbhimoveis.com.br/",
    "first_run_at": "...", "last_run_at": "...",
    "counts": {"active": 228, "active_rent": 29, "active_sale": 199, "removed": 0, ...},
    "property_types": {"rent": [{"id": 2, "name": "Apartamento"}, ...], "sale": [...]}
  },
  "listings": [
    {
      "id": "3240-sale",              // unique key: code + purpose
      "code": 3240,                    // the site's "Código"
      "purpose": "sale", "purpose_id": 2, "purpose_label": "Venda",
      "url": "https://www.rmbhimoveis.com.br/detalhes-imovel.php?imovel=3240&finalidade=2",
      "title": "Apartamento residencial de 196 m² à venda no Funcionários, em Belo Horizonte ...",
      "property_type": "Apartamento", "property_type_ids": [2],
      "price": 2450.0, "price_text": "R$ 2.450,00",
      "condo_fee": 1800.0, "iptu": 1035.0,
      "area_m2": 196.0, "area_source": "title",      // "title" | "description" | null
      "bedrooms": 4, "suites": 2, "bathrooms": 3, "parking_spaces": 2,
      "neighborhood": "Funcionários", "city": "Belo Horizonte", "state": "MG",
      "features": ["Academia", "Piscina", "1 Varanda", ...],
      "description": "LOCALIZAÇÃO; bairro Funcionários ...",
      "thumbnail": "https://cdn.imoview.com.br/...",
      "image_urls": ["https://cdn.imoview.com.br/rmimoveis/Imoveis/3240/....jpeg?...", ...],
      "images": [{"position": 0, "url": "...", "local_path": "images/3240-sale/000_xwdjx-....jpeg"}, ...],
      "contact_summary": "Olá, tenho interesse neste imóvel: Apartamento, Venda, 4 quartos, ...",
      "raw": {"card": {...}, "info_items": [...], "condo_fee_text": "...", "iptu_text": "..."},
      "status": "active",
      "first_seen": "...", "last_seen": "...", "updated_at": "...", "removed_at": null,
      "price_history": [{"date": "...", "price": 2450.0, "price_text": "R$ 2.450,00"}],
      "content_hash": "..."
    }
  ]
}
```

As of 2026-11-24 the site has **228 active listings** (29 for rent and 199 for sale) with about
4,900 photos (about 520 MB). The first run with `--images` takes about 10 minutes. Later
daily runs take about 2 minutes and download only new photos.

A real record is in [`docs/sample_listing.json`](docs/sample_listing.json).

Fields the site leaves empty (`--` on the cards) are stored as `null`. Prices are stored
exactly as the site shows them. Some sale prices appear to be entered in thousands, so
`price_text` is kept next to `price`. See [`docs/SITE_STUDY.md`](docs/SITE_STUDY.md).

## Slideshow viewer (`viewer/index.html`)

A single-file HTML/JS app that presents the listings from `data/listings.json` as a full-screen
slideshow.

```bash
python -m rmbh_scraper view       # or: it opens automatically after `crawl`
```

If you open the page directly as a file, the browser blocks the automatic JSON load. In that
case, pick or drag `data/listings.json` onto the page. Photos load from `data/images/` and fall
back to the CDN URL if a local file is missing.

- **Timing**: two independent clocks.
  - *Tempo entre fotos* (2–30 s) is how often the photo changes. It cycles through the house's
    photos, limited by *Fotos por imóvel*, and starts over when it runs out.
  - *Tempo entre imóveis* (5 s–5 min) is how long each house (or pair or trio) stays on screen.
  - The bar at the bottom shows the time left until the next house.
- **Menu (top-left button, or `M`)**: time between photos and between houses, houses at a time (1, 2 or 3),
  photos per house (1, 3, 5, 10 or all), image fit, filter (all, rent or sale), order (newest, price, shuffle),
  which overlay parts to show, play/pause, fullscreen and restart. Settings are remembered in the browser.
- **Layout**: 1 house fills the screen, 2 split it into left and right halves, 3 into three equal
  columns.
- **Image fit (Ajuste da imagem)**: *Imagem inteira* (default) shows the whole photo, fitted to
  the slot's width or height, never cropped. *Ajustar à largura* makes the photo exactly as wide
  as the slot, and *Ajustar à altura* exactly as tall. Either may crop or leave bars on the other
  axis, centred. *Preencher o quadro* zooms until the photo's smaller side fills the slot, so there
  are no bars and the edges are cropped.
- **Look**: a light theme (white, the default) and a dark theme; switch with *Tema* in the menu
  or the `T` key. The tag in each house's top-right corner shows *Aluguel* in teal or *Venda* in
  orange. The house code (number only) is in the top-left corner, the same size as the price.
  Photos change on their own; there is no key for stepping through them.
- **Details shown**: type, price (rent shown as "/ month"), neighbourhood and city, bedrooms,
  suites, bathrooms, parking, area ("~" means taken from the description), condo fee, IPTU,
  amenities, description, code, original title and photo counter. Fields the site doesn't
  provide are left out.
- **Keys**: `Space` play/pause, `←`/`→` previous/next house(s) (`↑`/`↓` and `PageUp`/`PageDown`,
  as sent by presentation clickers, do the same),
  `1` `2` `3` houses at a time, `Z` cycle image fit, `T` light/dark theme, `F` fullscreen.
- Optional URL parameters: `?data=path/to/listings.json&images=path/to/data/`.

## Python API

```python
from rmbh_scraper import RMBHClient, Crawler, RENT, SALE

c = RMBHClient()
c.get_property_types(SALE)                    # [{'id': 2, 'name': 'Apartamento'}, ...]
c.get_neighborhoods(SALE, property_type=2)    # [{'id': 44, 'name': 'Belvedere', 'city': ..., 'state': 'MG'}, ...]
c.search(SALE, property_type=2, bedrooms=3, neighborhoods=[44])   # result cards, all pages
for page in c.search_pages(RENT, property_type=1): ...            # page by page
c.get_listing(3240, SALE)                     # full detail dict, or None if not published

Crawler(c, data_dir="data", download_images=True).run()          # the daily job
```

## CLI

```bash
python -m rmbh_scraper types --purpose sale
python -m rmbh_scraper neighborhoods --purpose sale --type 2
python -m rmbh_scraper search --purpose rent --type 1
python -m rmbh_scraper search --purpose sale --type 2 --bedrooms 3 --neighborhood 44
python -m rmbh_scraper get 3240 --purpose sale
python -m rmbh_scraper crawl [--images] [--purpose rent] [--workers 4] [--delay 0.25] [--data-dir data] [--force] [--no-view] [--no-browser] [--fullscreen] [--port 8000]
python -m rmbh_scraper view [--data-dir data] [--port 8000] [--no-browser] [--fullscreen]
```

## Project layout

```
rmbh_scraper/
  client.py    requests session per search, retries/backoff, per-host throttle
  parsers.py   pure HTML -> dict parsers (types, neighbourhoods, result cards, detail page)
  crawler.py   full crawl, de-duplication, incremental merge, image download, reports
  cli.py       command line
  viewer.py    local web server for the slideshow (viewer/ + data/)
viewer/index.html        slideshow app
tools/network_study.py   Selenium + DevTools network recorder used to study the site
docs/SITE_STUDY.md       endpoints, parameters, quirks, data inventory
tests/                   parser + merge tests on saved HTML fixtures (pytest)
```

## Re-running the network study

```bash
pip install -r requirements-study.txt   # chromedriver-py must match your Chrome major version
python tools/network_study.py --out study_output [--chrome /path/to/chrome] [--headful]
```

This writes `study_output/network_log.json` (every request with its method, URL, POST body,
status and a preview of the XHR/document body) and an HTML snapshot of each step.

## Tests

```bash
pip install pytest && python -m pytest -q
```

## Versioning and releases

`.github/workflows/release.yml` versions the project automatically. On every push to the
default branch it runs the tests. If they pass, it creates the next `vX.Y.Z` tag and a GitHub
Release with auto-generated notes and a zip of the app (`rm-scraping-vX.Y.Z.zip`).

- The bump is worked out from the commit messages since the last tag:
  - **major**: a message contains `BREAKING CHANGE`, `type!:` or `[major]`.
  - **minor**: a subject starts with `Add`, `New` or `feat:`, or the message contains `[minor]`.
  - **patch**: anything else.
- The first release is `v1.0.0`.
- Put `[skip release]` in a commit message to push without releasing.
- To force a bump, use *Actions → Versão automática → Run workflow*.
- Preview the next version locally with `python tools/next_version.py`.
- Check the installed version with `python -m rmbh_scraper --version`. A git checkout reports the
  nearest tag; a release zip reports its stamped version.
