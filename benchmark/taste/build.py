"""Sections 4 and 5.1: items, exclusions, tags and Qloo resolution, from one chart snapshot.

Public output:  data/items_<snap>.json      every eligible item with its tags (no Qloo data)
Private output: spike/out/taste/<snap>/     iTunes and Wikidata responses, Qloo resolution, identity-check input

Usage: python benchmark/taste/build.py dev|eval [--no-qloo]
"""

import asyncio
import collections
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from common import (CITY_ISO, DATA, GENRE_LANG, GROUPS, MAJORITY_LANG, PRIVATE, ROOT, WITHIN, dump, fold,
                    giveaway, load, preset)

# Before any engine import: the Qloo key, and a private search cache shared by the dev and eval builds.
os.environ.setdefault("ROOM_DISK_CACHE", str(PRIVATE / "qloo_search_cache"))
os.environ.setdefault("QLOO_CONCURRENCY", "4")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

SNAP = sys.argv[1] if len(sys.argv) > 1 else "dev"
CHARTS = DATA / ("charts_dev_20261015.json" if SNAP == "dev" else "charts_eval.json")
OUT = PRIVATE / SNAP
OUT.mkdir(parents=True, exist_ok=True)
SHARED = PRIVATE / "lookups"          # iTunes and Wikidata answers, keyed by Apple ID; shared by both snapshots
SHARED.mkdir(parents=True, exist_ok=True)


# ---------- leads and credits ----------

ROLES = DATA / f"india_roles_{SNAP}.json"
COMPOSER_ONLY = {fold(n) for n in (load(ROLES)["composer_only"] if ROLES.exists() else [])}


def lead_of(entry: dict, group: str) -> dict | None:
    """4.1: the first credit link, keyed by its Apple ID; an entry whose first credit has no ID is excluded (4.4c).
    India: the first credit that is not on the blind, frozen composer-and-lyricist list (india_roles_<snap>.json);
    an entry credited to listed names alone is excluded."""
    credits = entry["credits"]
    if group == "in":
        credits = [c for c in credits if fold(c["name"]) not in COMPOSER_ONLY]
    if not credits or not credits[0].get("apple_id"):
        return None
    return credits[0]


def chart_index(snap: dict) -> dict:
    """Per city: leads (id -> {name, ranks}), every credited id, folded title-featured names, Shazam sets."""
    idx = {}
    for g, cities in GROUPS.items():
        for c in cities:
            ch = snap["apple_city"].get(c)
            if not ch:
                continue
            leads, credited, named = {}, set(), set()
            for e in ch["entries"]:
                ld = lead_of(e, g if g != "africa" else CITY_ISO[c])
                if ld:
                    d = leads.setdefault(ld["apple_id"], {"name": ld["name"], "ranks": [], "entries": []})
                    d["ranks"].append(e["rank"])
                    d["entries"].append({"song_id": e.get("song_id"), "album_id": e.get("album_id")})
                for x in e["credits"]:
                    if x.get("apple_id"):
                        credited.add(x["apple_id"])
                    named.add(fold(x["name"]))
                named.update(fold(x) for x in e.get("featured_in_title") or [])
            sz = snap["shazam_city"].get(c)
            sz_ids = {e["lead_apple_id"] for e in sz["entries"]} if sz else None
            sz_names = ({fold(p) for e in sz["entries"] for p in [*_split(e["credit"]), e["credit"], *_title_feats(e["title"])]}
                        if sz else None)
            idx[(g, c)] = {"leads": leads, "credited": credited, "named": named,
                           "shazam_ids": sz_ids, "shazam_names": sz_names,
                           "lead_missing_id": sum(1 for e in ch["entries"] if not lead_of(e, g if g != "africa" else CITY_ISO[c]))}
    return idx


def _split(credit: str) -> list[str]:
    import re
    return [p for p in re.split(r"\s*(?:,|&|\bx\b|\bfeat(?:uring)?\b\.?|\bft\b\.?|\bwith\b)\s*", credit or "", flags=re.I) if p]


def _title_feats(title: str) -> list[str]:
    import re
    return [a for m in re.findall(r"[\(\[](?:feat(?:uring)?\.?|ft\.?|with)\s+([^\)\]]+)[\)\]]", title or "", re.I)
            for a in _split(m)]


def absent(idx_b: dict, aid: str, name: str) -> bool:
    return aid not in idx_b["credited"] and fold(name) not in idx_b["named"]


def absent_shazam(idx_b: dict, aid: str, name: str):
    if idx_b["shazam_ids"] is None:
        return None
    return aid not in idx_b["shazam_ids"] and fold(name) not in idx_b["shazam_names"]


def on_shazam(idx_a: dict, aid: str, name: str):
    if idx_a["shazam_ids"] is None:
        return None
    return aid in idx_a["shazam_ids"] or fold(name) in idx_a["shazam_names"]


# ---------- items ----------

def make_items(snap: dict, idx: dict) -> tuple[list, list]:
    items, excluded = [], []
    for g, cities in GROUPS.items():
        live = [c for c in cities if (g, c) in idx]
        for a in live:
            A = idx[(g, a)]
            for aid, x in A["leads"].items():
                why = giveaway(x["name"])
                if why:
                    excluded.append({"group": g, "artist_id": aid, "artist": x["name"], "reason": f"giveaway: {why}"})
                    continue
                for b in live:
                    if b == a:
                        continue
                    B = idx[(g, b)]
                    kind = None
                    if absent(B, aid, x["name"]) and absent_shazam(B, aid, x["name"]) is not False:
                        kind = "presence"
                    elif aid in B["leads"] and min(x["ranks"]) + 10 <= min(B["leads"][aid]["ranks"]):
                        kind = "rank_gap"
                    if kind:
                        items.append({"group": g, "artist_id": aid, "artist": x["name"], "gold": a, "other": b,
                                      "kind": kind, "best_rank_gold": min(x["ranks"]), "entries_gold": len(x["ranks"]),
                                      "shazam_confirmed": bool(on_shazam(A, aid, x["name"]) and
                                                               absent_shazam(B, aid, x["name"])),
                                      "shazam_gold": on_shazam(A, aid, x["name"]),
                                      "shazam_other": on_shazam(B, aid, x["name"])})
    # One copy per (artist, gold, other): an artist excluded once stays out everywhere.
    seen, uniq = set(), []
    for it in items:
        k = (it["group"], it["artist_id"], it["gold"], it["other"])
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    ex_ids = {e["artist_id"] for e in excluded}
    return [i for i in uniq if i["artist_id"] not in ex_ids], excluded


def featured_items(snap: dict, idx: dict) -> list:
    """7.4 secondary set: X credited (not as lead) on A's Top 25 and absent from B's charts."""
    out = []
    for g, cities in GROUPS.items():
        if g == "africa":
            continue
        live = [c for c in cities if (g, c) in idx]
        for a in live:
            ch = snap["apple_city"][a]
            feat = {}
            for e in ch["entries"]:
                ld = lead_of(e, g)
                for x in e["credits"]:
                    if x.get("apple_id") and (not ld or x["apple_id"] != ld["apple_id"]):
                        feat.setdefault(x["apple_id"], {"name": x["name"], "co": set(), "ranks": []})
                        feat[x["apple_id"]]["co"].update(y["apple_id"] for y in e["credits"] if y.get("apple_id"))
                        feat[x["apple_id"]]["ranks"].append(e["rank"])
            for aid, x in feat.items():
                if aid in idx[(g, a)]["leads"] or giveaway(x["name"]):
                    continue
                for b in live:
                    if b != a and absent(idx[(g, b)], aid, x["name"]) and absent_shazam(idx[(g, b)], aid, x["name"]) is not False:
                        out.append({"group": g, "artist_id": aid, "artist": x["name"], "gold": a, "other": b,
                                    "kind": "featured", "co_credits": sorted(x["co"] - {aid}),
                                    "best_rank_gold": min(x["ranks"])})
    return out


# ---------- iTunes and Wikidata (4.6) ----------

def _http_json(url: str, data: bytes | None = None, headers: dict | None = None, pause: float = 3.2,
               retry_wait: float = 20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "RoomTasteTrack/1.0 (research)", **(headers or {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = json.loads(r.read().decode("utf-8"))
            time.sleep(pause)
            return body
        except Exception as e:  # iTunes answers 403 or 429 when hurried
            time.sleep(retry_wait * (attempt + 1))
            last = e
    raise last


def itunes_artists(ids: list[str], cc: str) -> dict:
    path = SHARED / "itunes_artists.json"
    have = load(path) if path.exists() else {}
    need = [i for i in ids if i not in have]
    for k in range(0, len(need), 150):
        batch = need[k:k + 150]
        res = _http_json(f"https://itunes.apple.com/lookup?id={','.join(batch)}&country={cc}")
        got = {str(r.get("artistId")): {"name": r.get("artistName"), "genre": r.get("primaryGenreName")}
               for r in res.get("results", []) if r.get("wrapperType") == "artist"}
        for i in batch:
            have[i] = got.get(i, {"name": None, "genre": None, "missing_in": cc})
        dump(path, have)
    return have


def itunes_first_releases(ids: list[str], cc: str) -> dict:
    """Earliest album or single release per artist: one lookup covers ten artists, up to 200 releases each."""
    path = SHARED / "itunes_first_release.json"
    have = load(path) if path.exists() else {}
    need = [i for i in ids if i not in have]
    for k in range(0, len(need), 10):
        batch = need[k:k + 10]
        res = _http_json(f"https://itunes.apple.com/lookup?id={','.join(batch)}&entity=album&limit=200&country={cc}")
        dates = collections.defaultdict(list)
        for r in res.get("results", []):
            if r.get("wrapperType") == "collection" and r.get("releaseDate"):
                dates[str(r.get("artistId"))].append(r["releaseDate"][:10])
        for i in batch:
            have[i] = min(dates[i]) if dates.get(i) else None
        dump(path, have)
    return have


def itunes_songs(ids: list[str], cc: str) -> dict:
    path = SHARED / "itunes_songs.json"
    have = load(path) if path.exists() else {}
    need = [i for i in ids if i and i not in have]
    for k in range(0, len(need), 150):
        batch = need[k:k + 150]
        res = _http_json(f"https://itunes.apple.com/lookup?id={','.join(batch)}&country={cc}")
        got = {str(r.get("trackId")): {"release": (r.get("releaseDate") or "")[:10],
                                       "collection": str(r.get("collectionId"))}
               for r in res.get("results", []) if r.get("wrapperType") == "track"}
        for i in batch:
            have[i] = got.get(i)
        dump(path, have)
    return have


def itunes_collections(ids: list[str], cc: str) -> dict:
    """Release date per album or single (the collection), for the album-drop tag."""
    path = SHARED / "itunes_collections.json"
    have = load(path) if path.exists() else {}
    need = [i for i in dict.fromkeys(ids) if i and i not in have]
    for k in range(0, len(need), 150):
        batch = need[k:k + 150]
        res = _http_json(f"https://itunes.apple.com/lookup?id={','.join(batch)}&country={cc}")
        got = {str(r.get("collectionId")): (r.get("releaseDate") or "")[:10]
               for r in res.get("results", []) if r.get("wrapperType") == "collection"}
        for i in batch:
            have[i] = got.get(i)
        dump(path, have)
    return have


# Reviewer hometown answers (4.6 blanks). Satellite places map to their pilot metro, as the 0.6-degree rule would.
SATELLITE = {"pretoria": "Johannesburg", "soweto": "Johannesburg", "brooklyn": "New York City", "bronx": "New York City",
             "the bronx": "New York City", "queens": "New York City", "harlem": "New York City", "new york": "New York City",
             "compton": "Los Angeles", "inglewood": "Los Angeles", "long beach": "Los Angeles", "brampton": "Toronto",
             "mississauga": "Toronto", "scarborough": "Toronto", "gurgaon": "Delhi", "gurugram": "Delhi", "noida": "Delhi",
             "new delhi": "Delhi", "thane": "Mumbai", "navi mumbai": "Mumbai", "bombay": "Mumbai", "bangalore": "Bengaluru",
             "fort worth": "Dallas", "arlington": "Dallas", "decatur": "Atlanta", "college park": "Atlanta",
             "oakland": "San Francisco", "washington": "Washington D.C.", "washington, d.c.": "Washington D.C.",
             "salford": "Manchester", "umlazi": "Durban", "ikeja": "Lagos"}


def reviewer_metro(answer: str | None) -> str | None:
    if not answer or fold(answer) in ("unknown", ""):
        return None
    f = fold(answer).split(",")[0].strip()
    if f == "elsewhere":
        return "elsewhere"
    for c in {c for cs in GROUPS.values() for c in cs}:
        if fold(c) == f:
            return c
    return SATELLITE.get(f) or SATELLITE.get(fold(answer)) or "elsewhere"


def wikidata_homes(ids: list[str]) -> dict:
    """Apple Music artist ID (P2850) -> place of birth (P19) or location of formation (P740), with coordinates."""
    path = SHARED / "wikidata_homes.json"
    have = load(path) if path.exists() else {}
    need = [i for i in ids if i not in have]
    for k in range(0, len(need), 40):
        batch = need[k:k + 40]
        q = ("SELECT ?id ?prop ?place ?coord WHERE { VALUES ?id { " + " ".join(f'"{i}"' for i in batch) + " } "
             "?item wdt:P2850 ?id . VALUES ?prop { wdt:P740 wdt:P19 } ?item ?prop ?place . ?place wdt:P625 ?coord . }")
        try:
            res = _http_json("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"}),
                             headers={"Accept": "application/sparql-results+json"}, pause=65, retry_wait=65)
        except Exception as e:  # Wikidata throttles hard at times; the batch stays unfilled and a later run retries it
            print(f"wikidata: batch {k // 40} skipped ({repr(e)[:80]})", flush=True)
            continue
        found = collections.defaultdict(list)
        for b in res["results"]["bindings"]:
            lon, lat = b["coord"]["value"].replace("Point(", "").rstrip(")").split()
            found[b["id"]["value"]].append({"prop": b["prop"]["value"].rsplit("/", 1)[-1], "place": b["place"]["value"],
                                            "lat": float(lat), "lon": float(lon)})
        for i in batch:
            have[i] = found.get(i, [])
        dump(path, have)
    return have


def home_metro(places: list) -> str | None:
    """The pilot city within 0.6 degrees of the artist's home place; formation place wins over birthplace."""
    import engine
    for p in sorted(places, key=lambda p: p["prop"] != "P740"):
        best, dist = None, 0.6 ** 2
        for c in {cc for cs in GROUPS.values() for cc in cs}:
            lat, lon, *_ = engine.PRESET[preset(c)]
            d = (lat - p["lat"]) ** 2 + (lon - p["lon"]) ** 2
            if d <= dist:
                best, dist = c, d
        if best:
            return best
        return "elsewhere"
    return None


def tags(snap: dict, idx: dict, items: list) -> dict:
    date = dt.date.fromisoformat(snap["evaluation_date"])
    by_group = collections.defaultdict(set)
    for it in items:
        by_group[it["group"]].add(it["artist_id"])
    store = {"us": "us", "gb": "gb", "ca": "ca", "za": "za", "in": "in", "africa": "ng"}
    artists, songs = {}, {}
    for g, ids in by_group.items():
        artists.update({k: v for k, v in itunes_artists(sorted(ids), store[g]).items() if k in ids})
        song_ids = [e["song_id"] for c in GROUPS[g] if (g, c) in idx for x in idx[(g, c)]["leads"].values()
                    for e in x["entries"]]
        songs.update(itunes_songs(song_ids, store[g]))
    first = {}
    for g, ids in by_group.items():
        first.update({k: v for k, v in itunes_first_releases(sorted(ids), store[g]).items() if k in ids})
    homes = wikidata_homes(sorted({i["artist_id"] for i in items}))
    idp = DATA / f"identity_{SNAP}.json"
    reviewer = load(idp).get("hometowns", {}) if idp.exists() else {}
    album_ids = [e["album_id"] for (g, c), v in idx.items() for x in v["leads"].values() for e in x["entries"]]
    released = {}
    for g in by_group:
        released.update({k: v for k, v in itunes_collections(album_ids, store[g]).items() if v})
    top100 = {cc: {x.get("apple_id") for e in ch["entries"] for x in e["credits"]}
              for cc, ch in snap["apple_country"].items()}
    national_cc = {"us": ["us"], "gb": ["gb"], "ca": ["ca"], "za": ["za"], "in": ["in"], "africa": ["ng", "ke", "gh", "za"]}
    charts_per = collections.Counter((g, aid) for (g, c), v in idx.items() for aid in v["credited"])
    for it in items:
        g, aid = it["group"], it["artist_id"]
        a = artists.get(aid) or {}
        it["genre"] = a.get("genre")
        it["language"] = GENRE_LANG.get(a.get("genre") or "", "other")
        it["same_language"] = it["language"] == MAJORITY_LANG[g]
        it["national"] = charts_per[(g, aid)] >= 2 or any(aid in top100.get(cc, set()) for cc in national_cc[g])
        fr = first.get(aid)
        it["first_release"] = fr
        it["tenure"] = None if not fr else ("established" if int(fr[:4]) <= 2023 else "new")
        hm = home_metro(homes.get(aid) or [])
        if hm is None:                       # Wikidata blank: the reviewers' answer, mapped to a pilot metro
            hm = reviewer_metro(reviewer.get(aid))
        it["home_metro"] = hm
        it["hometown"] = None if hm is None else (hm in (it["gold"], it["other"]))
        it["high_conf"] = it["best_rank_gold"] <= 15 or it.get("entries_gold", 1) >= 2
        # Album drop: 3+ of X's entries on A from one release (the chart's album link) dated 0 to 14 days before.
        ents = idx[(g, it["gold"])]["leads"][aid]["entries"]
        rel = collections.Counter(e["album_id"] for e in ents if released.get(e["album_id"])
                                  and 0 <= (date - dt.date.fromisoformat(released[e["album_id"]])).days <= 14)
        it["album_drop"] = bool(rel) and max(rel.values()) >= 3
    return {"artists": artists, "first_release": first, "homes": homes}


# ---------- Qloo resolution (5.1) ----------

async def resolve_all(names: dict) -> dict:
    import engine
    sem = asyncio.Semaphore(4)

    async def one(aid, name):
        async with sem:
            try:
                m = await engine.resolve(name, "artist")
            except Exception as e:
                return aid, {"error": repr(e)[:200]}
            hit = m.get("match") or {}
            return aid, {"query": name, "certain": bool(m.get("certain")), "quality": m.get("quality"),
                         "entity_id": hit.get("entity_id"), "name": hit.get("name"),
                         "disambiguation": hit.get("disambiguation"), "description": hit.get("description"),
                         "popularity": hit.get("popularity"), "tags": [t["name"] for t in (hit.get("tags") or [])[:6]]}

    return dict(await asyncio.gather(*[one(a, n) for a, n in names.items()]))


def main():
    snap = load(CHARTS)
    idx = chart_index(snap)
    items, excluded = make_items(snap, idx)
    feats = featured_items(snap, idx)
    side = tags(snap, idx, items)
    leads = {i["artist_id"]: i["artist"] for i in items}
    featured = {i["artist_id"]: i["artist"] for i in feats if i["artist_id"] not in leads}
    out = {"snapshot": snap.get("snapshot"), "evaluation_date": snap["evaluation_date"],
           "dropped_by_date_rule": snap.get("dropped_by_date_rule"), "items": items, "featured_items": feats,
           "excluded": excluded,
           "lead_entries_without_id": {f"{g}:{c}": v["lead_missing_id"] for (g, c), v in idx.items() if v["lead_missing_id"]}}
    dump(DATA / f"items_{SNAP}.json", out)
    by = collections.Counter(i["group"] for i in items)
    print(f"{len(items)} lead items over {len(leads)} artists {dict(by)}; {len(feats)} featured items over "
          f"{len(featured)} artists; {len(excluded)} excluded")
    if "--no-qloo" not in sys.argv:
        res = asyncio.run(resolve_all({**leads, **featured}))
        dump(OUT / "resolution.json", res)
        cert = sum(1 for a in leads if res[a].get("certain"))
        print(f"Qloo certain matches: {cert}/{len(leads)} lead artists")
        # The blind identity check sees Apple facts and Qloo facts, and nothing from any system.
        chk = []
        for aid, r in res.items():
            if not r.get("certain"):
                continue
            its = [i for i in items + feats if i["artist_id"] == aid]
            chk.append({"artist_id": aid, "role": "lead" if aid in leads else "featured",
                        "apple": {"credit": its[0]["artist"], "genre": (side["artists"].get(aid) or {}).get("genre"),
                                  "charts": sorted({i["gold"] for i in its}), "group": its[0]["group"],
                                  "home_metro": its[0].get("home_metro")},
                        "qloo": {k: r[k] for k in ("name", "disambiguation", "description", "tags")}})
        dump(OUT / "identity_input.json", chk)
        print(f"identity-check input: {len(chk)} artists")


if __name__ == "__main__":
    main()
