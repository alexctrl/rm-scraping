"""Full-site crawl + incremental merge into a JSON database.

Designed to run once a day:

1. Enumerate property types for each purpose (rent / sale).
2. Run one search per (purpose, type) – plus the broad type 0 search – and
   collect every result card. Searches are de-duplicated by (code, purpose).
3. Fetch the detail page of every listing (in parallel, throttled).
4. Merge with the previous database:
     * new listings          -> status "active", first_seen = today
     * still present         -> last_seen updated, changes recorded
     * missing from searches -> detail re-checked; "removed" if gone,
                                "unlisted" if the page still resolves
5. Optionally download images (only the ones not already on disk).
6. Write data/listings.json atomically + a run report in data/runs/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .client import PURPOSE_LABELS_PT, PURPOSES, RENT, SALE, RMBHClient

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# Fields compared between runs to detect a change in a listing.
TRACKED_FIELDS = (
    "title",
    "property_type",
    "price",
    "price_text",
    "condo_fee",
    "iptu",
    "area_m2",
    "bedrooms",
    "suites",
    "bathrooms",
    "parking_spaces",
    "neighborhood",
    "city",
    "features",
    "description",
    "image_urls",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def listing_key(code: int, purpose_id: int) -> str:
    return f"{code}-{PURPOSES.get(purpose_id, purpose_id)}"


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _image_filename(url: str, position: int) -> str:
    name = os.path.basename(urlparse(url).path) or f"{position:03d}.jpg"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return f"{position:03d}_{name}"


def build_record(card: dict[str, Any] | None, detail: dict[str, Any], type_ids: set[int]) -> dict[str, Any]:
    """Merge the search-result card and the detail page into one listing record."""
    card = card or {}
    purpose_id = detail["purpose_id"]
    image_urls = detail.get("images") or ([card["thumbnail"]] if card.get("thumbnail") else [])
    rec = {
        "id": listing_key(detail["code"], purpose_id),
        "code": detail["code"],
        "purpose": PURPOSES.get(purpose_id),
        "purpose_id": purpose_id,
        "purpose_label": PURPOSE_LABELS_PT.get(purpose_id),
        "url": detail["url"],
        "title": detail.get("title"),
        "property_type": card.get("property_type"),
        "property_type_ids": sorted(t for t in type_ids if t),
        "price": detail.get("price") if detail.get("price") is not None else card.get("price"),
        "price_text": detail.get("price_text") or card.get("price_text"),
        "condo_fee": detail.get("condo_fee"),
        "iptu": detail.get("iptu"),
        "area_m2": detail.get("area_m2"),
        "area_source": detail.get("area_source"),
        "bedrooms": card.get("bedrooms") if card.get("bedrooms") is not None else detail.get("bedrooms_from_title"),
        "suites": card.get("suites") if card.get("suites") is not None else detail.get("suites_from_title"),
        "bathrooms": card.get("bathrooms"),
        "parking_spaces": (
            card.get("parking_spaces") if card.get("parking_spaces") is not None else detail.get("parking_from_title")
        ),
        "neighborhood": card.get("neighborhood") or detail.get("neighborhood_from_title"),
        "city": detail.get("city"),
        "state": detail.get("state") or ("MG" if detail.get("city") == "Belo Horizonte" else None),
        "features": detail.get("features") or [],
        "description": detail.get("description"),
        "thumbnail": card.get("thumbnail") or (image_urls[0] if image_urls else None),
        "image_urls": image_urls,
        "images": [{"position": i, "url": u, "local_path": None} for i, u in enumerate(image_urls)],
        "contact_summary": detail.get("contact_summary"),
        "raw": {
            "card": card or None,
            "info_items": detail.get("info_items_raw"),
            "condo_fee_text": detail.get("condo_fee_text"),
            "iptu_text": detail.get("iptu_text"),
        },
    }
    rec["content_hash"] = hashlib.sha1(
        json.dumps({k: rec.get(k) for k in TRACKED_FIELDS}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return rec


class Crawler:
    def __init__(
        self,
        client: RMBHClient | None = None,
        data_dir: str | Path = "data",
        workers: int = 4,
        download_images: bool = False,
        min_ratio: float = 0.5,
        purposes: tuple[int, ...] = (RENT, SALE),
    ):
        self.client = client or RMBHClient()
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "listings.json"
        self.workers = workers
        self.download_images = download_images
        self.min_ratio = min_ratio
        self.purposes = purposes

    # ------------------------------------------------------------------ #
    def load_db(self) -> dict[str, Any]:
        if self.db_path.exists():
            with open(self.db_path, encoding="utf-8") as fh:
                return json.load(fh)
        return {"meta": {}, "listings": []}

    # ------------------------------------------------------------------ #
    def discover(self) -> tuple[dict[str, dict], dict[int, list[dict]]]:
        """Run every search; return {key: {'card', 'type_ids'}} and the type catalog."""
        catalog: dict[int, list[dict]] = {}
        jobs: list[tuple[int, int]] = []
        for p in self.purposes:
            types = self.client.get_property_types(p)
            catalog[p] = types
            jobs.append((p, 0))
            jobs.extend((p, t["id"]) for t in types)
        log.info("running %d searches", len(jobs))

        found: dict[str, dict] = {}
        type_names = {(p, t["id"]): t["name"] for p, ts in catalog.items() for t in ts}
        errors = []
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(self.client.search, p, t): (p, t) for p, t in jobs}
            for fut in as_completed(futs):
                p, t = futs[fut]
                try:
                    cards = fut.result()
                except Exception as e:  # noqa: BLE001
                    errors.append((p, t, repr(e)))
                    log.error("search purpose=%s type=%s failed: %s", p, t, e)
                    continue
                log.info("search purpose=%s type=%s (%s): %d results", p, t, type_names.get((p, t), "any"), len(cards))
                for c in cards:
                    key = listing_key(c["code"], c["purpose_id"])
                    entry = found.setdefault(key, {"card": c, "type_ids": set()})
                    entry["type_ids"].add(t)
        if errors:
            raise RuntimeError(f"{len(errors)} searches failed: {errors[:3]}")
        return found, catalog

    # ------------------------------------------------------------------ #
    def fetch_details(self, keys: list[tuple[int, int]]) -> dict[str, dict | None]:
        out: dict[str, dict | None] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(self.client.get_listing, c, p): (c, p) for c, p in keys}
            for i, fut in enumerate(as_completed(futs), 1):
                c, p = futs[fut]
                out[listing_key(c, p)] = fut.result()
                if i % 25 == 0:
                    log.info("details: %d/%d", i, len(keys))
        return out

    # ------------------------------------------------------------------ #
    def _download_images(self, records: list[dict[str, Any]]) -> tuple[int, int]:
        img_root = self.data_dir / "images"
        todo = []
        for rec in records:
            folder = img_root / rec["id"]
            for img in rec["images"]:
                path = folder / _image_filename(img["url"], img["position"])
                img["local_path"] = str(path.relative_to(self.data_dir))
                if not path.exists():
                    todo.append((img["url"], path))
        ok = failed = 0

        def _get(url: str, path: Path) -> None:
            data = self.client.download(url)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)

        log.info("downloading %d new images", len(todo))
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(_get, u, p): (u, p) for u, p in todo}
            for fut in as_completed(futs):
                try:
                    fut.result()
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    log.warning("image failed %s: %s", futs[fut][0], e)
        # drop local_path for files that failed
        for rec in records:
            for img in rec["images"]:
                if img["local_path"] and not (self.data_dir / img["local_path"]).exists():
                    img["local_path"] = None
        return ok, failed

    # ------------------------------------------------------------------ #
    def run(self, force: bool = False) -> dict[str, Any]:
        started = _now()
        db = self.load_db()
        previous: dict[str, dict] = {r["id"]: r for r in db.get("listings", [])}
        # Only listings of the purposes being crawled can be compared / removed
        # (a `--purpose rent` run must not touch sale listings).
        in_scope = {k: r for k, r in previous.items() if r.get("purpose_id") in self.purposes}
        prev_active = sum(1 for r in in_scope.values() if r.get("status") == "active")

        found, catalog = self.discover()
        log.info("discovered %d unique listings", len(found))

        if prev_active and len(found) < prev_active * self.min_ratio and not force:
            raise RuntimeError(
                f"Only {len(found)} listings found vs {prev_active} active last run; "
                "refusing to mark the rest as removed (site problem?). Use --force to override."
            )

        missing = [k for k, r in in_scope.items() if k not in found and r.get("status") != "removed"]
        detail_keys = [(e["card"]["code"], e["card"]["purpose_id"]) for e in found.values()]
        detail_keys += [(previous[k]["code"], previous[k]["purpose_id"]) for k in missing]
        details = self.fetch_details(detail_keys)

        now = _now()
        report: dict[str, Any] = {"started_at": started, "added": [], "changed": [], "removed": [], "unlisted": []}
        listings: dict[str, dict] = dict(previous)

        for key, entry in found.items():
            det = details.get(key)
            if det is None:
                # In search results but detail page empty: keep card-only data.
                log.warning("detail missing for %s; using card data only", key)
                card = entry["card"]
                det = {
                    "code": card["code"],
                    "purpose_id": card["purpose_id"],
                    "url": card["url"],
                    "images": [],
                }
            rec = build_record(entry["card"], det, entry["type_ids"])
            old = previous.get(key)
            self._merge(rec, old, now, report)
            listings[key] = rec

        for key in missing:
            old = previous[key]
            det = details.get(key)
            if det is None:
                old["status"] = "removed"
                old["removed_at"] = now
                report["removed"].append(key)
            else:
                rec = build_record(old.get("raw", {}).get("card"), det, set(old.get("property_type_ids", [])))
                self._merge(rec, old, now, report)
                rec["status"] = "unlisted"
                listings[key] = rec
                report["unlisted"].append(key)

        active = [r for r in listings.values() if r.get("status") in ("active", "unlisted")]
        if self.download_images:
            ok, failed = self._download_images(active)
            report["images_downloaded"], report["images_failed"] = ok, failed
        else:
            # keep local paths of images downloaded on previous runs
            for rec in active:
                for img in rec["images"]:
                    path = self.data_dir / "images" / rec["id"] / _image_filename(img["url"], img["position"])
                    img["local_path"] = str(path.relative_to(self.data_dir)) if path.exists() else None

        ordered = sorted(listings.values(), key=lambda r: (r.get("status") != "active", r["purpose_id"], -r["code"]))
        counts = {
            "total_records": len(ordered),
            "active": sum(1 for r in ordered if r.get("status") == "active"),
            "unlisted": sum(1 for r in ordered if r.get("status") == "unlisted"),
            "removed": sum(1 for r in ordered if r.get("status") == "removed"),
            "active_rent": sum(1 for r in ordered if r.get("status") == "active" and r["purpose_id"] == RENT),
            "active_sale": sum(1 for r in ordered if r.get("status") == "active" and r["purpose_id"] == SALE),
        }
        db = {
            "meta": {
                "schema_version": SCHEMA_VERSION,
                "source": self.client.base_url,
                "last_run_at": now,
                "first_run_at": db.get("meta", {}).get("first_run_at") or now,
                "counts": counts,
                "property_types": {PURPOSES[p]: ts for p, ts in catalog.items()},
            },
            "listings": ordered,
        }
        _atomic_write_json(self.db_path, db)

        report["finished_at"] = _now()
        report["counts"] = counts
        stamp = report["finished_at"].replace(":", "").replace("+0000", "Z")
        _atomic_write_json(self.data_dir / "runs" / f"{stamp}.json", report)
        log.info(
            "done: %d active (%d new, %d changed, %d removed, %d unlisted)",
            counts["active"],
            len(report["added"]),
            len(report["changed"]),
            len(report["removed"]),
            len(report["unlisted"]),
        )
        return report

    # ------------------------------------------------------------------ #
    @staticmethod
    def _merge(rec: dict[str, Any], old: dict[str, Any] | None, now: str, report: dict[str, Any]) -> None:
        rec["status"] = "active"
        rec["last_seen"] = now
        rec["removed_at"] = None
        if not old:
            rec["first_seen"] = now
            rec["updated_at"] = now
            rec["price_history"] = [{"date": now, "price": rec["price"], "price_text": rec["price_text"]}]
            report["added"].append(rec["id"])
            return
        rec["first_seen"] = old.get("first_seen") or now
        rec["price_history"] = list(old.get("price_history") or [])
        if old.get("status") == "removed":
            report["added"].append(rec["id"])  # re-listed
        if rec["content_hash"] != old.get("content_hash"):
            changed = [f for f in TRACKED_FIELDS if rec.get(f) != old.get(f)]
            rec["updated_at"] = now
            report["changed"].append({"id": rec["id"], "fields": changed})
        else:
            rec["updated_at"] = old.get("updated_at") or now
        if rec["price"] != old.get("price"):
            rec["price_history"].append({"date": now, "price": rec["price"], "price_text": rec["price_text"]})
