"""Record the network traffic of a real browser session on rmbhimoveis.com.br.

This is the reverse-engineering tool used to discover the endpoints the
requests-only client relies on. It drives Chromium with Selenium, enables
Chrome's performance log (DevTools Network domain) and, for each step, dumps
every request (method, URL, POST body, resource type, status, mime type)
plus the response body of XHR/Document requests.

Usage:
    pip install -r requirements-study.txt
    python tools/network_study.py --out study_output [--chrome /path/to/chrome] [--headful]

Output: study_output/network_log.json and one HTML snapshot per step.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

BASE = "https://www.rmbhimoveis.com.br/"
SKIP_EXT = (".css", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".svg", ".ttf", ".ico")


def make_driver(chrome: str | None, headful: bool) -> webdriver.Chrome:
    o = Options()
    if chrome:
        o.binary_location = chrome
    if not headful:
        o.add_argument("--headless=new")
    for a in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=1366,900"):
        o.add_argument(a)
    if os.environ.get("HTTPS_PROXY"):
        o.add_argument("--proxy-server=" + os.environ["HTTPS_PROXY"])
    o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    service = None
    try:  # prefer a pinned driver from chromedriver-py if installed
        from chromedriver_py import binary_path

        service = Service(executable_path=binary_path)
    except ImportError:
        pass
    return webdriver.Chrome(options=o, service=service) if service else webdriver.Chrome(options=o)


def collect(driver: webdriver.Chrome, step: str) -> list[dict]:
    reqs: dict[str, dict] = {}
    for entry in driver.get_log("performance"):
        msg = json.loads(entry["message"])["message"]
        p = msg.get("params", {})
        if msg["method"] == "Network.requestWillBeSent":
            r = p["request"]
            url = r["url"]
            if "rmbhimoveis" not in url or url.split("?")[0].lower().endswith(SKIP_EXT):
                continue
            reqs[p["requestId"]] = {
                "step": step,
                "method": r["method"],
                "url": url,
                "post_data": r.get("postData"),
                "type": p.get("type"),
            }
        elif msg["method"] == "Network.responseReceived" and p["requestId"] in reqs:
            reqs[p["requestId"]].update(status=p["response"]["status"], mime=p["response"].get("mimeType"))
    out = []
    for rid, r in reqs.items():
        if r.get("type") in ("XHR", "Fetch", "Document"):
            try:
                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
                r["body_preview"] = body.get("body", "")[:3000]
            except Exception:  # body not retained (redirects etc.)
                r["body_preview"] = None
        out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="study_output")
    ap.add_argument("--chrome", default=os.environ.get("CHROME_BIN"))
    ap.add_argument("--headful", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    d = make_driver(a.chrome, a.headful)
    d.execute_cdp_cmd("Network.enable", {})
    log: list[dict] = []

    def snap(name: str, wait: float = 5) -> None:
        time.sleep(wait)
        log.extend(collect(d, name))
        (out / f"{name}.html").write_text(d.page_source, encoding="utf-8")
        print(f"[{name}] {d.current_url}")

    try:
        d.get(BASE)
        snap("01_home")
        d.find_element(By.ID, "BtCheckVenda").click()  # "Comprar" = sale (FINALIDADEIMOVEL=2)
        snap("02_click_comprar", 3)
        d.execute_script("document.querySelector('button[name=buscar]').click()")
        snap("03_search_results")
        nxt = d.find_elements(By.PARTIAL_LINK_TEXT, "Próximo")
        if nxt:
            nxt[0].click()
            snap("04_results_page2")
        first = d.find_element(By.CSS_SELECTOR, 'a[href*="detalhes-imovel.php"]').get_attribute("href")
        d.get(first)
        snap("05_detail")
    finally:
        d.quit()

    (out / "network_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(log)} requests recorded -> {out / 'network_log.json'}")
    for r in log:
        if r.get("type") in ("XHR", "Fetch", "Document"):
            print(f"  {r['step']:<20} {r['method']:<4} {r.get('status')} {r['url']}  {r.get('post_data') or ''}")


if __name__ == "__main__":
    main()
