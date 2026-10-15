"""Taste track ground truth: Apple Music City Charts (Top 25 per city), all fetched the same day.

Apple describes the city charts as plays plus other signs of local momentum, updated daily.
Playlist IDs come from the music.apple.com/{storefront}/new/top-charts pages. Raw pages stay in
spike/out/taste_raw/ (ignored); the answer key is benchmark/taste_charts.json.

Polite: one request at a time with a pause. No Qloo or Gemini calls here.

Usage: python benchmark/taste/fetch_dev_top25.py [--offline]. Superseded by fetch.py --dev for the pilot.
"""

import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "spike" / "out" / "taste_raw"
OUT = ROOT / "spike" / "out" / "taste_charts_dev_top25.json"
UA = "Mozilla/5.0"
OFFLINE = "--offline" in sys.argv

# Country groups. Every city here has an Apple Music "Top 25: <City>" chart.
GROUPS = {
    "us": ["New York City", "Los Angeles", "Atlanta", "Dallas", "Houston", "Miami", "Nashville", "Chicago",
           "Austin", "Denver", "Detroit", "Honolulu", "San Francisco", "Seattle", "Washington D.C."],
    "gb": ["London", "Manchester", "Birmingham", "Glasgow", "Liverpool"],
    "ca": ["Toronto", "Vancouver", "Calgary", "Edmonton", "Ottawa", "Winnipeg"],
    "za": ["Johannesburg", "Cape Town", "Durban"],
    "in": ["Mumbai", "Delhi", "Bengaluru"],
    "africa": ["Lagos", "Accra", "Nairobi", "Johannesburg"],
}


def slug(city: str) -> str:
    return "top-25-" + re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def get(url: str, name: str) -> tuple[str, str]:
    path = RAW / name
    if OFFLINE and path.exists():
        return path.read_text(encoding="utf-8"), json.loads((RAW / (name + ".meta.json")).read_text())["fetched_at"]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode("utf-8", "replace")
    at = now()
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    (RAW / (name + ".meta.json")).write_text(json.dumps({"url": url, "fetched_at": at}))
    time.sleep(1.5)
    return body, at


def playlist_ids() -> dict:
    """slug -> (storefront, playlist id), read from the saved top-charts pages."""
    ids = {}
    for page in sorted((ROOT / "spike" / "out" / "hometurf_raw").glob("apple_charts_*.html")):
        sf = "us" if "cities_us" in page.name else page.stem.split("_")[-1]
        for s, pid in re.findall(r'/playlist/(top-25-[a-z0-9\-]+)/(pl\.[0-9a-f]{32})', page.read_text(encoding="utf-8", errors="replace")):
            ids.setdefault(s, (sf, pid))
    return ids


SPLIT = re.compile(r"\s*(?:,|&|\bx\b|\bX\b|\bfeat\.?|\bft\.?|\bwith\b)\s*", re.I)
FEAT = re.compile(r"[\(\[](?:feat\.?|ft\.?|with)\s+([^\)\]]+)[\)\]]", re.I)


def split_credit(credit: str) -> list[str]:
    return [a.strip() for a in SPLIT.split(credit or "") if a and a.strip()]


def chart(city: str, ids: dict) -> dict:
    s = slug(city)
    sf, pid = ids[s]
    url = f"https://music.apple.com/{sf}/playlist/{s}/{pid}"
    html, at = get(url, f"apple_{s}.html")
    ld = json.loads(re.search(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S).group(1))
    data = json.loads(re.search(r'id="serialized-server-data">(.*?)</script>', html, re.S).group(1))
    items = next(x["items"] for x in data["data"][0]["data"]["sections"]
                 if x.get("items") and "artistName" in x["items"][0])
    entries = []
    for rank, it in enumerate(items, 1):
        artists = [{"name": x["title"],
                    "apple_id": ((((x.get("segue") or {}).get("destination") or {}).get("contentDescriptor") or {})
                                 .get("identifiers") or {}).get("storeAdamID")}
                   for x in it.get("subtitleLinks") or []]
        if not artists:
            artists = [{"name": a, "apple_id": None} for a in split_credit(it.get("artistName", ""))]
        feat = [a for m in FEAT.findall(it["title"]) for a in split_credit(m)]
        entries.append({"rank": rank, "title": it["title"], "credit": it.get("artistName"),
                        "artists": artists, "featured_in_title": feat})
    return {"city": city, "url": url, "title": ld.get("name"), "published": ld.get("datePublished"),
            "fetched_at": at, "entries": entries}


def main():
    ids = playlist_ids()
    cities = sorted({c for cs in GROUPS.values() for c in cs})
    charts, errors = {}, {}
    for c in cities:
        try:
            charts[c] = chart(c, ids)
            print(f"{c:18} {len(charts[c]['entries']):3} entries  published {charts[c]['published']}")
        except Exception as e:  # report, keep going
            errors[c] = repr(e)[:200]
            print(f"{c:18} FAILED {errors[c]}")
    OUT.write_text(json.dumps({"source": "Apple Music City Charts, Top 25", "groups": GROUPS,
                               "charts": charts, "errors": errors}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({len(charts)} charts, {len(errors)} errors)")


if __name__ == "__main__":
    main()
