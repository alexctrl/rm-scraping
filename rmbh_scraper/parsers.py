"""HTML parsers for www.rmbhimoveis.com.br.

The site is a server-rendered PHP app (Imoview CRM theme by Universal Software).
There is no JSON API: every endpoint returns HTML fragments or pages, so all
structure extraction happens here. Parsers are pure functions (HTML in, dicts
out) so they can be unit-tested against saved fixtures.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")
_MONEY = re.compile(r"R\$\s*:?\s*([\d.]+(?:,\d{1,2})?)")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = _WS.sub(" ", text).strip()
    return text or None


def parse_money(text: str | None) -> float | None:
    """'R$ 2.450,00' -> 2450.0 ; 'R$: 1800,00' -> 1800.0 ; '--' -> None."""
    if not text:
        return None
    m = _MONEY.search(text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


# --------------------------------------------------------------------------- #
# Search option endpoints (AJAX fragments)
# --------------------------------------------------------------------------- #
def parse_property_types(html: str) -> list[dict[str, Any]]:
    """Busca/consulta_tipoimo.php -> [{'id': 2, 'name': 'Apartamento'}, ...].

    The response is a bare list of <option> tags interleaved with debug text
    ("numero registro: N<br/>").
    """
    out = []
    for opt in _soup(html).find_all("option"):
        value = (opt.get("value") or "").strip()
        name = clean(opt.get_text())
        if value.isdigit() and name:
            out.append({"id": int(value), "name": name})
    return out


_BAIRRO_LABEL = re.compile(r"^(?P<name>.+?)\s*\((?P<city>.+?)\s*-\s*(?P<state>[A-Z]{2})\)\s*$")


def parse_neighborhoods(html: str) -> list[dict[str, Any]]:
    """Busca/consulta_bairros.php -> [{'id': 44, 'name': 'Belvedere', 'city': ..., 'state': ...}]."""
    out = []
    for inp in _soup(html).select('input[name="BAIRRO[]"]'):
        value = (inp.get("value") or "").strip()
        label = clean(inp.parent.get_text()) if inp.parent else None
        if not value.isdigit() or not label:
            continue
        item: dict[str, Any] = {"id": int(value), "name": label, "city": None, "state": None}
        m = _BAIRRO_LABEL.match(label)
        if m:
            item.update(m.groupdict())
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# Listing (search results) page
# --------------------------------------------------------------------------- #
def _detail_params(href: str) -> tuple[int | None, int | None]:
    q = parse_qs(urlparse(href).query)
    try:
        return int(q["imovel"][0]), int(q["finalidade"][0])
    except (KeyError, ValueError, IndexError):
        return None, None


def parse_listing_cards(html: str) -> list[dict[str, Any]]:
    """Parse the property cards in listagem-de-imoveis.php (also used on the home page).

    Card fields: thumbnail, type, price, suites/bedrooms/bathrooms/parking, neighbourhood.
    """
    cards = []
    seen = set()
    for box in _soup(html).select("div.thumbnails.carrossel_style"):
        a = box.select_one('a[href*="detalhes-imovel.php"]')
        if not a:
            continue
        code, purpose_id = _detail_params(a["href"])
        if code is None or (code, purpose_id) in seen:
            continue
        seen.add((code, purpose_id))
        img = box.select_one("img")
        stats = {}
        for opt in box.select(".div_options"):
            label = clean(opt.select_one(".options-carrossel").get_text()) if opt.select_one(".options-carrossel") else None
            val = clean(opt.select_one(".text-options").get_text()) if opt.select_one(".text-options") else None
            if label:
                stats[label.lower()] = val
        price_el = box.select_one(".valor_imovel")
        price_text = clean(price_el.get_text()) if price_el else None
        type_el = box.select_one(".bairro_carrossel")
        loc_el = box.select_one(".text-localizacao")
        cards.append(
            {
                "code": code,
                "purpose_id": purpose_id,
                "url": a["href"],
                "thumbnail": img.get("src") if img else None,
                "property_type": clean(type_el.get_text()) if type_el else None,
                "price_text": price_text,
                "price": parse_money(price_text),
                "suites": parse_int(stats.get("suítes")),
                "bedrooms": parse_int(stats.get("quartos")),
                "bathrooms": parse_int(stats.get("banhos")),
                "parking_spaces": parse_int(stats.get("vagas")),
                "neighborhood": clean(loc_el.get_text()) if loc_el else None,
            }
        )
    return cards


_SHOWING = re.compile(r"Mostrando\s*(\d+)\s*a\s*(\d+)\s*de\s*(\d*)", re.S)


def parse_listing_page(html: str) -> dict[str, Any]:
    """Return cards plus pagination metadata for one results page."""
    total = first = last_on_page = None
    m = _SHOWING.search(html)
    if m:
        first, last_on_page = int(m.group(1)), int(m.group(2))
        total = int(m.group(3)) if m.group(3) else 0
    soup = _soup(html)
    has_next = False
    last_page = None
    menu = soup.select_one("#menu")
    if menu:
        for a in menu.select("a[href]"):
            txt = clean(a.get_text()) or ""
            pm = re.search(r"pagina=(\d+)", a["href"])
            if not pm:
                continue
            if txt.startswith("Próximo"):
                has_next = True
            elif txt.startswith("Último"):
                last_page = int(pm.group(1))
    return {
        "total": total,
        "first": first,
        "last": last_on_page,
        "has_next": has_next,
        "last_page": last_page,
        "cards": parse_listing_cards(html),
    }


# --------------------------------------------------------------------------- #
# Detail page
# --------------------------------------------------------------------------- #
_CODE = re.compile(r"Código:\s*(\d+)")
_AREA = re.compile(r"(\d+(?:[.,]\d+)?)\s*m²")
_ROOMS = re.compile(r"(\d+)\s*quartos?", re.I)
_SPOTS = re.compile(r"(\d+)\s*vagas?", re.I)
# "Apartamento residencial de 196 m² à venda no Funcionários, em Belo Horizonte no valor de ..."
_TITLE_A = re.compile(r"\b(?:à venda|para (?:aluguel|locação|venda)|para alugar)\s+n[oa]s?\s+(?P<nb>.+?),\s*em\s+(?P<city>.+?)\s+no valor", re.I)
# "Casa Comercial para aluguel, 4 vagas, Lourdes - Belo Horizonte/MG no valor de R$ 20.000,00"
_TITLE_B = re.compile(r",\s*(?P<nb>[^,]+?)\s+-\s+(?P<city>[^/,]+?)/(?P<state>[A-Z]{2})\s+no valor", re.I)

_FEE_CONDO = re.compile(r"^Condom[íi]nio", re.I)
_FEE_IPTU = re.compile(r"^IPTU", re.I)
_PRICE_ONLY = re.compile(r"^R\$\s*[\d.,]+$")
_DISCLAIMER = "As informações dos imóveis exibidos neste site"


def parse_detail(html: str) -> dict[str, Any] | None:
    """Parse detalhes-imovel.php. Returns None when the listing doesn't exist.

    The server answers HTTP 200 with an empty template for unknown or inactive
    listings (and for a wrong `finalidade`), so existence is detected by the
    presence of the "Código: N" header.
    """
    soup = _soup(html)
    code_el = soup.find("span", class_="titulo_h1")
    m = _CODE.search(code_el.get_text()) if code_el else None
    if not m:
        return None
    code = int(m.group(1))

    h1 = soup.select_one("h1.titulo_h1")
    title = clean(h1.get_text()) if h1 else None

    # --- gallery (full-size links; <img src> is the same URL) -------------
    images: list[str] = []
    for a in soup.select(".imagem_galeria_detalhes a[href]"):
        href = a["href"].strip()
        if href and href not in images:
            images.append(href)
    if not images:
        for img in soup.select(".imagem_galeria_detalhes img[src]"):
            if img["src"] not in images:
                images.append(img["src"])

    # --- info chips: features + fees + price -----------------------------
    features: list[str] = []
    condo_text = iptu_text = price_text = None
    info_items = [clean(x.get_text()) for x in soup.select(".item_info")]
    info_items = [x for x in info_items if x]
    for item in info_items:
        if _FEE_CONDO.match(item) and "R$" in item:
            condo_text = item
        elif _FEE_IPTU.match(item):
            iptu_text = item
        elif _PRICE_ONLY.match(item):
            price_text = item
        else:
            features.append(item)

    # --- description -------------------------------------------------------
    description = None
    head = soup.find("h3", string=re.compile("Descrição do imóvel"))
    if head:
        col = head.find_parent(class_="col-xs-12")
        body = col.find_next_sibling("div") if col else None
        if body:
            for p in body.find_all("p"):
                if _DISCLAIMER in p.get_text():
                    p.decompose()
            for br in body.find_all("br"):
                br.replace_with("\n")
            text = body.get_text()
            text = "\n".join(_WS.sub(" ", ln).strip() for ln in text.splitlines())
            description = re.sub(r"\n{3,}", "\n\n", text).strip() or None

    # --- title-derived attributes -----------------------------------------
    area = bedrooms = parking = None
    neighborhood = city = state = None
    if title:
        am = _AREA.search(title)
        if am:
            area = float(am.group(1).replace(".", "").replace(",", "."))
        rm = _ROOMS.search(title)
        bedrooms = int(rm.group(1)) if rm else None
        sm = _SPOTS.search(title)
        parking = int(sm.group(1)) if sm else None
        tm = _TITLE_A.search(title)
        if tm:
            neighborhood, city = clean(tm.group("nb")), clean(tm.group("city"))
        else:
            tm = _TITLE_B.search(title)
            if tm:
                neighborhood, city, state = clean(tm.group("nb")), clean(tm.group("city")), tm.group("state")
        if not price_text:
            pm = re.search(r"no valor de\s+(.+)$", title)
            if pm:
                price_text = clean(pm.group(1))

    # Inquiry form pre-fills a summary, e.g.
    # "Olá, tenho interesse neste imóvel: Apartamento, Venda, 4 quartos, R$ 2.450,00, Funcionários."
    summary = None
    ta = soup.select_one("textarea[name=MENSAGEM]")
    if ta:
        summary = clean(ta.get_text())

    return {
        "code": code,
        "title": title,
        "price_text": price_text,
        "price": parse_money(price_text),
        "condo_fee_text": condo_text,
        "condo_fee": parse_money(condo_text),
        "iptu_text": iptu_text,
        "iptu": parse_money(iptu_text),
        "area_m2": area,
        "bedrooms_from_title": bedrooms,
        "parking_from_title": parking,
        "neighborhood_from_title": neighborhood,
        "city": city,
        "state": state,
        "features": features,
        "description": description,
        "images": images,
        "contact_summary": summary,
        "info_items_raw": info_items,
    }
