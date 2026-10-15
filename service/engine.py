"""Room's scoring engine.

A reference is scored with one Qloo heatmap over a MULTIPOLYGON of every city in the room
plus a fixed set of anchor cities. Qloo ranks heatmap affinity across the whole polygon, so
every city sits on one scale and scores stay comparable between requests.

Per city:
  known = cells with signal for the reference / cells for a universal baseline of the same type
  loved = median affinity of those cells (the age-filtered heatmap when an age band is set)
"""

import asyncio
import difflib
import re
import statistics

from cache import cached, Cache
from qloo import qloo, entities, QlooError

TYPES = {
    "artist": "urn:entity:artist",
    "book": "urn:entity:book",
    "brand": "urn:entity:brand",
    "destination": "urn:entity:destination",
    "movie": "urn:entity:movie",
    "person": "urn:entity:person",
    "place": "urn:entity:place",
    "podcast": "urn:entity:podcast",
    "tv_show": "urn:entity:tv_show",
    "videogame": "urn:entity:videogame",
}

# A reference everyone in a market knows, per type. Its cell count is the "fully known" mark.
BASELINES = {
    "artist": "Beyonce",
    "brand": "Coca-Cola",
    "tv_show": "Friends",
    "movie": "Titanic",
    "person": "Barack Obama",
    "book": "Harry Potter and the Philosopher's Stone",
    "podcast": "The Joe Rogan Experience",
    "videogame": "Minecraft",
    "destination": "Paris",
    "place": "Coca-Cola",
}
BASELINE_TYPE = {"place": "brand"}

# Fixed anchors keep the affinity scale stable whatever cities a user picks.
ANCHORS = ["New York", "Los Angeles", "London", "Johannesburg", "Lagos"]

# Seeded coordinates for common cities: (lat, lon, half-height deg, half-width deg).
PRESET = {
    "New York": (40.71, -73.97, 0.22, 0.25),
    "Los Angeles": (34.05, -118.30, 0.25, 0.30),
    "London": (51.51, -0.12, 0.20, 0.30),
    "Johannesburg": (-26.17, 28.04, 0.20, 0.22),
    "Lagos": (6.53, 3.38, 0.15, 0.25),
    "Dallas": (32.78, -96.80, 0.22, 0.25),
    "Atlanta": (33.75, -84.39, 0.20, 0.22),
    "Philadelphia": (39.95, -75.16, 0.15, 0.18),
    "Toronto": (43.70, -79.40, 0.18, 0.25),
    "Chicago": (41.85, -87.70, 0.22, 0.20),
    "Houston": (29.76, -95.37, 0.25, 0.28),
    "Miami": (25.78, -80.21, 0.18, 0.15),
    "Harare": (-17.83, 31.05, 0.12, 0.14),
    "Cape Town": (-33.93, 18.47, 0.15, 0.15),
    "Nairobi": (-1.29, 36.82, 0.12, 0.14),
    "Accra": (5.60, -0.19, 0.12, 0.15),
    "Manchester": (53.48, -2.24, 0.12, 0.15),
    "Paris": (48.86, 2.35, 0.15, 0.20),
    "Mumbai": (19.08, 72.88, 0.18, 0.12),
    "Sydney": (-33.87, 151.10, 0.25, 0.25),
}

AGES = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"]

THIN = 40  # baseline cells below this make a city's score low-confidence


# ---------- cities ----------

def _bbox(wkt: str):
    nums = [float(x) for x in re.findall(r"-?\d+\.\d+|-?\d+", wkt or "")]
    if len(nums) < 6:
        return None
    lons, lats = nums[0::2], nums[1::2]
    return min(lats), max(lats), min(lons), max(lons)


async def city(name: str) -> dict:
    """Resolve a city name to a box. Presets first, then Qloo locality search."""
    clean = name.strip()
    for k, (lat, lon, hh, hw) in PRESET.items():
        if k.lower() == clean.lower():
            return {"name": k, "lat": lat, "lon": lon, "hh": hh, "hw": hw, "label": k}

    async def look():
        body = await qloo.get("/search", {"query": clean, "types": "urn:entity:locality", "take": 1})
        hits = entities(body)
        if not hits or not hits[0].get("location"):
            return None
        h = hits[0]
        lat, lon = h["location"]["lat"], h["location"]["lon"]
        hh, hw = 0.18, 0.2
        bb = _bbox((h.get("properties") or {}).get("boundaries", ""))
        if bb:
            hh = min(0.3, max(0.08, (bb[1] - bb[0]) / 2))
            hw = min(0.35, max(0.08, (bb[3] - bb[2]) / 2))
        return {"name": h["name"], "lat": lat, "lon": lon, "hh": hh, "hw": hw,
                "label": h.get("disambiguation") or h["name"]}

    found = await cached(Cache.key("city", clean.lower()), look)
    if not found:
        raise ValueError(f"Qloo has no locality called {clean}")
    return found


def _polygon(cities: list[dict]) -> str:
    parts = []
    for c in cities:
        s, n = round(c["lat"] - c["hh"], 4), round(c["lat"] + c["hh"], 4)
        w, e = round(c["lon"] - c["hw"], 4), round(c["lon"] + c["hw"], 4)
        parts.append(f"(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))")
    return "MULTIPOLYGON(" + ",".join(parts) + ")"


def _owner(lat: float, lon: float, cities: list[dict]):
    best, dist = None, 1e9
    for c in cities:
        if abs(lat - c["lat"]) <= c["hh"] + 0.02 and abs(lon - c["lon"]) <= c["hw"] + 0.02:
            d = (lat - c["lat"]) ** 2 + (lon - c["lon"]) ** 2
            if d < dist:
                best, dist = c["name"], d
    return best


async def room(names: list[str]) -> list[dict]:
    """User cities plus anchors, de-duplicated, in a stable order."""
    seen, out = set(), []
    resolved = await asyncio.gather(*[city(n) for n in list(names) + ANCHORS])
    for c in resolved:
        if c["name"] not in seen:
            seen.add(c["name"])
            out.append(c)
    return sorted(out, key=lambda c: c["name"])


# ---------- search ----------

def _slim(e: dict) -> dict:
    props = e.get("properties") or {}
    img = (props.get("image") or {}).get("url")
    return {
        "entity_id": e["entity_id"],
        "name": e.get("name"),
        "type": next((t.split(":")[-1] for t in (e.get("types") or [e.get("subtype") or ""])), None),
        "popularity": e.get("popularity"),
        "disambiguation": e.get("disambiguation"),
        "description": props.get("short_description") or (props.get("description") or "")[:160],
        "image": img,
        "tags": [{"id": t.get("tag_id") or t.get("id"), "name": t.get("name"), "kind": t.get("type")}
                 for t in (e.get("tags") or [])[:12]],
    }


async def search(name: str, etype: str | None, take: int = 5) -> list[dict]:
    async def look():
        p = {"query": name, "take": take}
        if etype in TYPES:
            p["types"] = TYPES[etype]
        return [_slim(e) for e in entities(await qloo.get("/search", p))]

    return await cached(Cache.key("search", name.lower(), etype, take), look)


def match_quality(query: str, hit_name: str) -> float:
    a, b = query.lower().strip(), (hit_name or "").lower().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return difflib.SequenceMatcher(None, a, b).ratio()


async def resolve(name: str, etype: str) -> dict:
    hits = await search(name, etype)
    if not hits:
        hits = await search(name, None)
    if not hits:
        return {"match": None, "candidates": [], "certain": False}
    ranked = sorted(hits, key=lambda h: (-match_quality(name, h["name"]), -(h.get("popularity") or 0)))
    best = ranked[0]
    q = match_quality(name, best["name"])
    return {"match": best, "candidates": ranked[:5], "certain": q >= 0.8, "quality": round(q, 2)}


# ---------- heatmap profile ----------

async def profile(entity_id: str, cities: list[dict], age: str | None = None) -> dict:
    """Cells and affinity per city for one entity over the room polygon."""
    poly = _polygon(cities)

    async def run():
        body = await qloo.get("/v2/insights", {
            "filter.type": "urn:heatmap",
            "filter.location": poly,
            "signal.interests.entities": entity_id,
            "signal.demographics.age": age,
            "take": 50,
        })
        cells = ((body or {}).get("results") or {}).get("heatmap") or []
        per: dict[str, list[float]] = {}
        for x in cells:
            loc, q = x.get("location") or {}, x.get("query") or {}
            owner = _owner(loc.get("latitude", 0), loc.get("longitude", 0), cities)
            if owner and q.get("affinity") is not None:
                per.setdefault(owner, []).append(q["affinity"])
        out = {}
        for c in cities:
            v = per.get(c["name"], [])
            out[c["name"]] = {
                "cells": len(v),
                "median": round(statistics.median(v), 4) if v else None,
                "p75": round(statistics.quantiles(v, n=4)[2], 4) if len(v) >= 4 else None,
            }
        return {"cities": out, "total": len(cells)}

    return await cached(Cache.key("profile", entity_id, poly, age), run)


async def baseline_id(etype: str) -> str:
    btype = BASELINE_TYPE.get(etype, etype)
    hit = await resolve(BASELINES.get(etype, "Coca-Cola"), btype)
    return hit["match"]["entity_id"]


# ---------- verdicts ----------

VERDICTS = {
    "lands": "They know it and they love it.",
    "roast": "They know it and keep their distance. Good for a jab.",
    "inside": "A slice of the room knows it. The ones who do, love it.",
    "dies": "A blank for most of the room.",
    "global": "Known worldwide. Qloo holds no local map for it.",
    "famous": "Famous everywhere, with a thin fan base here. Expect recognition and little love.",
    "unscored": "Qloo holds too little on this one to call it.",
}

VALUE = {"lands": 1.0, "roast": 0.8, "famous": 0.7, "global": 0.7, "inside": 0.4, "dies": 0.0}

# Global popularity percentile at which a name is famous beyond its fans.
# Whataburger sits at 0.98 and stays local; Nickelback and Drake sit above this line.
FAMOUS = 0.995


def verdict(known: float, loved: float | None, popularity: float = 0) -> str:
    if known < 0.45 and popularity >= FAMOUS:
        return "famous"
    if known < 0.15:
        return "dies"
    if known < 0.45:
        return "inside"
    if loved is not None and loved < 0.45:
        return "roast"
    return "lands"


async def score(entity: dict, etype: str, names: list[str], age: str | None = None) -> dict:
    cities = await room(names)
    base_id = await baseline_id(etype)
    calls = [profile(entity["entity_id"], cities), profile(base_id, cities)]
    if age:
        calls.append(profile(entity["entity_id"], cities, age))
    results = await asyncio.gather(*calls)
    prof, base = results[0], results[1]
    aged = results[2] if age else None

    wanted = list(dict.fromkeys(c["name"] for c in await asyncio.gather(*[city(n) for n in names])))
    out = {"entity_id": entity["entity_id"], "mode": "map", "cities": {}, "elsewhere": None, "age": age}

    if prof["total"] == 0:
        pop = entity.get("popularity") or 0
        v = "global" if pop >= 0.97 else "unscored"
        out["mode"] = "global"
        for n in wanted:
            out["cities"][n] = {"verdict": v, "known": round(pop, 2), "loved": None,
                                "confidence": "low", "why": VERDICTS[v], "cells": 0, "base_cells": None}
        return out

    rows = {}
    for c in cities:
        n = c["name"]
        cells = prof["cities"][n]["cells"]
        bcells = base["cities"][n]["cells"]
        known = min(1.0, cells / max(bcells, 1))
        loved = (aged["cities"][n]["median"] if aged else prof["cities"][n]["median"]) if cells >= 5 else None
        v = verdict(known, loved, entity.get("popularity") or 0)
        rows[n] = {
            "verdict": v,
            "known": round(known, 2),
            "loved": round(loved, 2) if loved is not None else None,
            "confidence": "low" if bcells < THIN else "high",
            "why": VERDICTS[v],
            "cells": cells,
            "base_cells": bcells,
        }
    for n in wanted:
        out["cities"][n] = rows[n]
    home = max(rows, key=lambda n: (rows[n]["known"], rows[n]["loved"] or 0))
    out["elsewhere"] = {"city": home, **rows[home]}
    return out


# ---------- swaps ----------

def _swap_tags(entity: dict) -> list[str]:
    tags = entity.get("tags") or []
    rank = lambda t: (0 if ":genre:" in (t["id"] or "") else 1 if ":keyword:" in (t["id"] or "") else 2)
    return [t["id"] for t in sorted(tags, key=rank) if t.get("id")][:3]


async def swap_candidates(entity: dict, etype: str, city_name: str, exclude: set | None = None) -> list[dict]:
    c = await city(city_name)
    ftype = TYPES[etype]
    tags = _swap_tags(entity)
    jobs = [qloo.get("/v2/insights", {
        "filter.type": ftype, "signal.interests.entities": entity["entity_id"],
        "signal.location.query": c["name"], "filter.exclude.entities": entity["entity_id"], "take": 10,
    })]
    if tags:
        jobs.append(qloo.get("/v2/insights", {
            "filter.type": ftype, "filter.tags": ",".join(tags),
            "signal.location.query": c["name"], "filter.exclude.entities": entity["entity_id"], "take": 12,
        }))
    seen, out = set(exclude or ()) | {entity["entity_id"]}, []
    for res in await asyncio.gather(*jobs, return_exceptions=True):
        if isinstance(res, Exception):
            continue
        for e in entities(res):
            if e["entity_id"] not in seen:
                seen.add(e["entity_id"])
                s = _slim(e)
                s["local_affinity"] = (e.get("query") or {}).get("affinity")
                out.append(s)
    return out


__all__ = ["TYPES", "AGES", "VALUE", "VERDICTS", "city", "room", "search", "resolve", "score",
           "swap_candidates", "QlooError"]
