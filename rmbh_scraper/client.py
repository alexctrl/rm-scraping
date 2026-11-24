"""Requests-only client for www.rmbhimoveis.com.br.

Endpoints discovered by recording the browser's network traffic (see
docs/SITE_STUDY.md and tools/network_study.py):

  GET  /Busca/consulta_tipoimo.php?FINALIDADEIMOVEL={1|2}        -> <option> list of property types
  GET  /Busca/consulta_bairros.php?TIPOIMO=..&FINALIDADEIMOVEL=.. -> neighbourhood checkboxes
  POST /Busca/tratar_busca.php                                    -> stores search filters in the PHP session
  GET  /listagem-de-imoveis.php?pagina=N                          -> results for the session's search (8/page)
  GET  /detalhes-imovel.php?imovel={code}&finalidade={1|2}        -> listing detail page

`finalidade` / `FINALIDADEIMOVEL`: 1 = Aluguel (rent), 2 = Venda (sale).

Searches are *stateful*: the filters live in the PHPSESSID session, so every
search uses its own `requests.Session`. Detail pages are stateless.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import parsers

log = logging.getLogger(__name__)

BASE_URL = "https://www.rmbhimoveis.com.br/"
RENT, SALE = 1, 2
PURPOSES = {RENT: "rent", SALE: "sale"}
PURPOSE_LABELS_PT = {RENT: "Aluguel", SALE: "Venda"}
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


class RMBHClient:
    """Thin, polite HTTP client around the site's PHP endpoints."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        min_interval: float = 0.25,
        user_agent: str = DEFAULT_UA,
        retries: int = 5,
        image_min_interval: float = 0.05,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.min_interval = min_interval
        self.user_agent = user_agent
        self.retries = retries
        self.image_min_interval = image_min_interval
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}
        self._shared = self._new_session()

    # ------------------------------------------------------------------ #
    # plumbing
    # ------------------------------------------------------------------ #
    def _new_session(self) -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=self.retries,
            connect=self.retries,
            read=self.retries,
            status=self.retries,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Referer": self.base_url,
            }
        )
        return s

    def _throttle(self, url: str) -> None:
        """Per-host politeness delay (the image CDN is throttled separately from the site)."""
        host = urlparse(url).netloc
        interval = self.min_interval if host == urlparse(self.base_url).netloc else self.image_min_interval
        if interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._last_request.get(host, 0.0) + interval)
            self._last_request[host] = slot
        if slot > now:
            time.sleep(slot - now)

    def _request(self, session: requests.Session, method: str, path: str, **kw) -> requests.Response:
        url = path if path.startswith("http") else self.base_url + path.lstrip("/")
        self._throttle(url)
        resp = session.request(method, url, timeout=self.timeout, **kw)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        return resp

    # ------------------------------------------------------------------ #
    # search options
    # ------------------------------------------------------------------ #
    def get_property_types(self, purpose: int) -> list[dict[str, Any]]:
        """Property types offered for a purpose (1=rent, 2=sale)."""
        r = self._request(self._shared, "GET", "Busca/consulta_tipoimo.php", params={"FINALIDADEIMOVEL": purpose})
        return parsers.parse_property_types(r.text)

    def get_neighborhoods(self, purpose: int, property_type: int) -> list[dict[str, Any]]:
        """Neighbourhoods that have listings for (purpose, property type)."""
        r = self._request(
            self._shared,
            "GET",
            "Busca/consulta_bairros.php",
            params={"TIPOIMO": property_type, "FINALIDADEIMOVEL": purpose},
        )
        return parsers.parse_neighborhoods(r.text)

    # ------------------------------------------------------------------ #
    # search
    # ------------------------------------------------------------------ #
    def search_pages(
        self,
        purpose: int,
        property_type: int = 0,
        bedrooms: int | None = None,
        neighborhoods: Iterable[int] | None = None,
        min_price: str | None = None,
        max_price: str | None = None,
        max_pages: int = 500,
    ) -> Iterator[dict[str, Any]]:
        """Run a search and yield each parsed results page.

        `property_type=0` acts as a broad "any type" search on the server, but it
        does not return every listing; for a complete crawl iterate all types
        (see crawler.py). An empty TIPOIMO returns nothing.
        """
        s = self._new_session()
        self._request(s, "GET", "")  # obtain PHPSESSID
        data: list[tuple[str, str]] = [
            ("FINALIDADEIMOVEL", str(purpose)),
            ("TIPOIMO", str(property_type)),
            ("QUARTOS", "" if bedrooms is None else str(bedrooms)),
            ("VALORMINIMO", min_price or ""),
            ("VALORMAXIMO", max_price or ""),
            ("CODIMOVEL", ""),
            ("buscar", "Buscar"),
        ]
        for nb in neighborhoods or ():
            data.append(("BAIRRO[]", str(nb)))
        self._request(s, "POST", "Busca/tratar_busca.php", data=data)

        seen: set[tuple[int, int]] = set()
        page = 1
        while page <= max_pages:
            r = self._request(s, "GET", "listagem-de-imoveis.php", params={"pagina": page})
            parsed = parsers.parse_listing_page(r.text)
            new = [c for c in parsed["cards"] if (c["code"], c["purpose_id"]) not in seen]
            parsed["page"] = page
            parsed["cards"] = new
            if not new:
                break
            seen.update((c["code"], c["purpose_id"]) for c in new)
            yield parsed
            if not parsed["has_next"]:
                break
            page += 1

    def search(self, purpose: int, property_type: int = 0, **kw) -> list[dict[str, Any]]:
        """Run a search and return all result cards (all pages)."""
        cards: list[dict[str, Any]] = []
        for page in self.search_pages(purpose, property_type, **kw):
            cards.extend(page["cards"])
        return cards

    # ------------------------------------------------------------------ #
    # detail
    # ------------------------------------------------------------------ #
    def detail_url(self, code: int, purpose: int) -> str:
        return f"{self.base_url}detalhes-imovel.php?imovel={code}&finalidade={purpose}"

    def get_listing(self, code: int, purpose: int) -> dict[str, Any] | None:
        """Fetch and parse one listing. Returns None if it is not published."""
        r = self._request(
            self._shared, "GET", "detalhes-imovel.php", params={"imovel": code, "finalidade": purpose}
        )
        d = parsers.parse_detail(r.text)
        if d is not None:
            d["purpose_id"] = purpose
            d["purpose"] = PURPOSES.get(purpose)
            d["url"] = self.detail_url(code, purpose)
        return d

    # ------------------------------------------------------------------ #
    # images
    # ------------------------------------------------------------------ #
    def download(self, url: str) -> bytes:
        r = self._request(self._shared, "GET", url)
        return r.content
