"""Section 2.2: the evaluation snapshot. Apple Music city Top 25, country Top 100, Shazam city Top 50.

Every page is saved raw (private), with its URL, fetch time, sha256 and Apple's datePublished. The date rule
(2.3) keeps the modal Apple publish date; a city chart on another date is refetched once, then dropped.

Usage:
  python benchmark/taste/fetch.py --eval      fetch now, write data/charts_eval.json
  python benchmark/taste/fetch.py --dev       re-parse the 15 Oct pages into data/charts_dev_20261015.json
"""

import collections
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request

from common import DATA, GROUPS, PRIVATE, ROOT, SHAZAM_COUNTRY, TOP100, CITY_ISO, dump

UA = "Mozilla/5.0"
CITIES = sorted({c for cs in GROUPS.values() for c in cs})
COUNTRIES = ["us", "gb", "ca", "za", "in", "ng", "ke", "gh"]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def slug(city: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")


def playlist_ids() -> dict:
    ids = {}
    for page in sorted((ROOT / "spike" / "out" / "hometurf_raw").glob("apple_charts_*.html")):
        sf = "us" if "cities_us" in page.name else page.stem.split("_")[-1]
        for s, pid in re.findall(r'/playlist/(top-25-[a-z0-9\-]+)/(pl\.[0-9a-f]{32})',
                                 page.read_text(encoding="utf-8", errors="replace")):
            ids.setdefault(s, (sf, pid))
    return ids


class Pages:
    def __init__(self, folder, offline=False):
        self.dir, self.offline = folder, offline

    def get(self, url: str, name: str):
        path = self.dir / name
        meta = self.dir / (name + ".meta.json")
        if self.offline == "cache" and path.exists() or self.offline is True:
            if not path.exists():
                return None, None
            m = json.loads(meta.read_text()) if meta.exists() else {"fetched_at": None, "status": 200}
            return path.read_bytes(), m
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            body, status = b"", e.code
        m = {"url": url, "fetched_at": now(), "status": status, "sha256": hashlib.sha256(body).hexdigest()}
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        meta.write_text(json.dumps(m))
        time.sleep(1.5)
        return (body if status == 200 else None), m


def apple_entries(html: str) -> tuple[dict, list]:
    ld = json.loads(re.search(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S).group(1))
    data = json.loads(re.search(r'id="serialized-server-data">(.*?)</script>', html, re.S).group(1))
    items = next(x["items"] for x in data["data"][0]["data"]["sections"]
                 if x.get("items") and "artistName" in x["items"][0])
    out = []
    for rank, it in enumerate(items, 1):
        credits = []
        for x in it.get("subtitleLinks") or []:
            cd = (((x.get("segue") or {}).get("destination") or {}).get("contentDescriptor") or {})
            credits.append({"name": x["title"], "apple_id": (cd.get("identifiers") or {}).get("storeAdamID")})
        album = None
        for x in it.get("tertiaryLinks") or []:
            cd = (((x.get("segue") or {}).get("destination") or {}).get("contentDescriptor") or {})
            album = (cd.get("identifiers") or {}).get("storeAdamID") or album
        feat = [a.strip() for m in re.findall(r"[\(\[](?:feat\.?|ft\.?|with)\s+([^\)\]]+)[\)\]]", it["title"], re.I)
                for a in re.split(r"\s*(?:,|&)\s*", m) if a.strip()]
        out.append({"rank": rank, "title": it["title"], "credit": it.get("artistName"), "credits": credits,
                    "featured_in_title": feat, "composer": it.get("composer"),
                    "song_id": ((it.get("contentDescriptor") or {}).get("identifiers") or {}).get("storeAdamID"),
                    "album_id": album})
    return {"title": ld.get("name"), "published": ld.get("datePublished")}, out


def shazam_entries(html: str) -> tuple[dict, list]:
    title = (re.search(r"<title>([^<]*)</title>", html) or [None, ""])[1]
    songs = re.findall(r'href="/song/(\d+)/[^"]*">([^<]+)<', html)
    arts = re.findall(r'href="/artist/[^"]*/(\d+)">([^<]+)</a>', html)
    unesc = lambda s: s.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')
    out = [{"rank": i, "title": unesc(t), "credit": unesc(a), "lead_apple_id": aid, "song_id": sid}
           for i, ((sid, t), (aid, a)) in enumerate(zip(songs, arts), 1)]
    return {"title": title}, out


def fetch(pages: Pages, ids: dict) -> dict:
    snap = {"apple_city": {}, "apple_country": {}, "shazam_city": {}, "missing": {}}
    for c in CITIES:
        s = "top-25-" + slug(c)
        if s not in ids:
            snap["missing"][f"apple:{c}"] = "no playlist id"
            continue
        sf, pid = ids[s]
        url = f"https://music.apple.com/{sf}/playlist/{s}/{pid}"
        body, m = pages.get(url, f"apple_{s}.html")
        if body is None:
            snap["missing"][f"apple:{c}"] = f"status {m and m.get('status')}"
            continue
        head, entries = apple_entries(body.decode("utf-8", "replace"))
        snap["apple_city"][c] = {"url": url, **head, **(m or {}), "entries": entries}
    for cc in COUNTRIES:
        sf, s, pid = TOP100[cc]
        url = f"https://music.apple.com/{sf}/playlist/{s}/{pid}"
        body, m = pages.get(url, f"apple_{s}.html")
        if body is None:
            snap["missing"][f"top100:{cc}"] = f"status {m and m.get('status')}"
            continue
        head, entries = apple_entries(body.decode("utf-8", "replace"))
        snap["apple_country"][cc] = {"url": url, **head, **(m or {}), "entries": entries}
    for c in CITIES:
        url = f"https://www.shazam.com/charts/top-50/{SHAZAM_COUNTRY[CITY_ISO[c]]}/{slug(c)}"
        body, m = pages.get(url, f"shazam_{slug(c)}.html")
        if body is None:
            snap["missing"][f"shazam:{c}"] = f"status {m and m.get('status')}"
            continue
        head, entries = shazam_entries(body.decode("utf-8", "replace"))
        # A city URL that falls back to the country chart is ignored (Nairobi covers all of Kenya).
        city_scope = c.split()[0].lower() in head["title"].lower() or ("new york" in head["title"].lower())
        if not city_scope or not entries:
            snap["missing"][f"shazam:{c}"] = f"not a city chart: {head['title'][:60]}"
            continue
        snap["shazam_city"][c] = {"url": url, **head, **(m or {}), "entries": entries}
    return snap


def date_rule(snap: dict, pages: Pages, ids: dict, refetch: bool) -> dict:
    days = {c: (v.get("published") or "")[:10] for c, v in snap["apple_city"].items()}
    mode = collections.Counter(days.values()).most_common(1)[0][0]
    dropped = {}
    for c, d in sorted(days.items()):
        if d == mode:
            continue
        if refetch:
            s = "top-25-" + slug(c)
            sf, pid = ids[s]
            body, m = pages.get(f"https://music.apple.com/{sf}/playlist/{s}/{pid}", f"apple_{s}.refetch.html")
            if body:
                head, entries = apple_entries(body.decode("utf-8", "replace"))
                if (head.get("published") or "")[:10] == mode:
                    snap["apple_city"][c] = {**snap["apple_city"][c], **head, **m, "entries": entries}
                    continue
        dropped[c] = d
        snap["apple_city"].pop(c)
    snap["evaluation_date"] = mode
    snap["dropped_by_date_rule"] = dropped
    return snap


def main():
    ids = playlist_ids()
    if "--dev" in sys.argv:
        # Dev pages: the 15 Oct Top 25s (benchmark/taste_fetch.py) and Shazam for the ten hometurf cities.
        # Dev pages: the 15 Oct Top 25s from benchmark/taste_fetch.py, plus Top 100 and Shazam pages fetched
        # the same evening into the same folder (read back from disk on every later run).
        pages = Pages(ROOT / "spike" / "out" / "taste_raw", offline="cache")
        snap = fetch(pages, ids)
        snap = date_rule(snap, pages, ids, refetch=False)
        snap["snapshot"] = "dev, 2026-10-15"
        dump(DATA / "charts_dev_20261015.json", snap)
    elif "--eval" in sys.argv:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M")
        pages = Pages(PRIVATE / "pages" / stamp)
        snap = fetch(pages, ids)
        snap = date_rule(snap, pages, ids, refetch=True)
        snap["snapshot"] = f"evaluation, fetched {stamp} UTC"
        dump(DATA / "charts_eval.json", snap)
    else:
        print(__doc__)
        return
    print(f"evaluation date {snap['evaluation_date']}; apple cities {len(snap['apple_city'])}, "
          f"top100 {len(snap['apple_country'])}, shazam cities {len(snap['shazam_city'])}; "
          f"dropped {snap['dropped_by_date_rule']}; missing {len(snap['missing'])}")
    for k, v in sorted(snap["missing"].items()):
        print("  missing", k, v)


if __name__ == "__main__":
    main()
