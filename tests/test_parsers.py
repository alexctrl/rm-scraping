from pathlib import Path

import pytest

from rmbh_scraper import parsers
from rmbh_scraper.crawler import Crawler, build_record

FIX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_money():
    assert parsers.parse_money("R$ 2.450,00") == 2450.0
    assert parsers.parse_money("R$440.000,00") == 440000.0
    assert parsers.parse_money("Condomínio R$: 1800,00") == 1800.0
    assert parsers.parse_money("IPTU: R$ 4173,05") == 4173.05
    assert parsers.parse_money("Valor sob consulta") is None
    assert parsers.parse_money(None) is None


def test_property_types():
    types = parsers.parse_property_types(read("tipoimo.html"))
    assert {"id": 2, "name": "Apartamento"} in types
    assert all(isinstance(t["id"], int) and t["name"] for t in types)


def test_neighborhoods():
    nbs = parsers.parse_neighborhoods(read("bairros.html"))
    assert nbs and nbs[0]["id"] == 18
    assert nbs[0]["name"] == "Anchieta"
    assert nbs[0]["city"] == "Belo Horizonte" and nbs[0]["state"] == "MG"


def test_listing_page():
    page = parsers.parse_listing_page(read("listing_page1.html"))
    assert page["total"] == 119
    assert page["has_next"] and page["last_page"] == 15
    assert len(page["cards"]) == 8
    c = page["cards"][0]
    assert c["code"] == 2809 and c["purpose_id"] == 2
    assert c["price"] == 440000.0 and c["bedrooms"] == 3 and c["suites"] is None
    assert c["thumbnail"].startswith("https://cdn.imoview.com.br/")


def test_listing_last_page():
    page = parsers.parse_listing_page(read("listing_last.html"))
    assert not page["has_next"]
    assert 0 < len(page["cards"]) <= 8


def test_detail_sale():
    d = parsers.parse_detail(read("detail_sale.html"))
    assert d["code"] == 3240
    assert d["area_m2"] == 196.0
    assert d["neighborhood_from_title"] == "Funcionários" and d["city"] == "Belo Horizonte"
    assert d["condo_fee"] == 1800.0 and d["iptu"] == 1035.0 and d["price"] == 2450.0
    assert "Piscina" in d["features"]
    assert not any("R$" in f for f in d["features"])
    assert len(d["images"]) > 10 and len(set(d["images"])) == len(d["images"])
    assert d["description"].startswith("LOCALIZAÇÃO")
    assert "As informações dos imóveis" not in d["description"]


def test_detail_rent():
    d = parsers.parse_detail(read("detail_rent.html"))
    assert d["code"] == 3222
    assert d["price"] == 20000.0 and d["iptu"] == 4173.05 and d["condo_fee"] is None
    assert d["neighborhood_from_title"] == "Lourdes" and d["state"] == "MG"
    assert d["parking_from_title"] == 4


def test_detail_missing():
    assert parsers.parse_detail(read("detail_missing.html")) is None


def _record(price=440000.0):
    card = parsers.parse_listing_page(read("listing_page1.html"))["cards"][0]
    card = dict(card, price=price)
    det = parsers.parse_detail(read("detail_sale.html"))
    det.update(purpose_id=2, url="u", code=card["code"], price=price)
    return build_record(card, det, {0, 2})


def test_merge_tracks_changes():
    report = {"added": [], "changed": [], "removed": [], "unlisted": []}
    first = _record()
    Crawler._merge(first, None, "t1", report)
    assert report["added"] == [first["id"]] and first["first_seen"] == "t1"
    second = _record(price=430000.0)
    Crawler._merge(second, first, "t2", report)
    assert second["first_seen"] == "t1" and second["last_seen"] == "t2"
    assert report["changed"][0]["fields"] == ["price"]
    assert [h["price"] for h in second["price_history"]] == [440000.0, 430000.0]
    assert second["property_type_ids"] == [2]
