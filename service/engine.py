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
import unicodedata

import llm
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
    # Every city with an Apple Music city chart in the Taste track, so a name never resolves to a namesake.
    "Austin": (30.27, -97.74, 0.15, 0.18),
    "Denver": (39.74, -104.99, 0.15, 0.18),
    "Detroit": (42.36, -83.10, 0.15, 0.20),
    "Honolulu": (21.33, -157.85, 0.08, 0.12),
    "Nashville": (36.16, -86.78, 0.15, 0.18),
    "San Francisco": (37.75, -122.35, 0.15, 0.15),
    "Seattle": (47.61, -122.33, 0.15, 0.15),
    "Washington D.C.": (38.90, -77.03, 0.15, 0.18),
    "Birmingham": (52.48, -1.90, 0.12, 0.18),
    "Glasgow": (55.86, -4.25, 0.10, 0.18),
    "Liverpool": (53.41, -2.95, 0.10, 0.12),
    "Vancouver": (49.25, -123.05, 0.15, 0.25),
    "Calgary": (51.05, -114.07, 0.15, 0.20),
    "Edmonton": (53.55, -113.49, 0.15, 0.20),
    "Ottawa": (45.40, -75.70, 0.15, 0.20),
    "Winnipeg": (49.88, -97.14, 0.12, 0.18),
    "Durban": (-29.86, 31.00, 0.15, 0.15),
    "Delhi": (28.62, 77.20, 0.20, 0.22),
    "Bengaluru": (12.97, 77.59, 0.15, 0.15),
}

AGES = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"]

THIN = 40  # baseline cells below this make a city's score low-confidence
MIN_MATCH = 0.65  # below this a search hit is a different thing with a similar name


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


_STOP = {"the", "a", "an", "of", "and", "&", "fc", "f.c.", "f.c", "inc", "ltd", "co"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[\w'.-]+", s.lower()) if t not in _STOP}


def _plain(s: str) -> str:
    # "Beyoncé" and "Beyonce", "’" and "'" compare as the same name.
    s = unicodedata.normalize("NFKD", s or "").replace("’", "'").replace("‘", "'")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).casefold().strip()


def match_quality(query: str, hit_name: str) -> float:
    a, b = _plain(query), _plain(hit_name)
    if a == b:
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    if ta and ta == tb:
        return 0.95                       # "Arsenal" and "Arsenal F.C."
    if ta and ta < tb and len(tb - ta) <= 1:
        return 0.85                       # "In-N-Out" and "In-N-Out Burger"
    if tb and tb < ta:
        return MIN_MATCH - 0.01           # the hit drops a word the writer wrote: "Nviiri the Storyteller" is not "The Storyteller"
    # "Republic" inside "Chicken Republic" is something else.
    if (a in b or b in a) and min(len(a), len(b)) / max(len(a), len(b)) >= 0.6:
        return 0.85
    q = difflib.SequenceMatcher(None, a, b).ratio()
    # Spelling alone misleads on short names ("Tml Vibez" reads 0.82 against "Mo Vibez"):
    # a match also has to share most of its words.
    if ta and tb and len(ta & tb) / len(ta | tb) < 0.5:
        q = min(q, MIN_MATCH - 0.01)
    return q


def _rank(name: str, hits: list[dict]) -> list[dict]:
    return sorted(hits, key=lambda h: (-match_quality(name, h["name"]), -(h.get("popularity") or 0)))


async def resolve(name: str, etype: str) -> dict:
    """Best entity of the requested type. A weak or off-type match comes back unmatched,
    with Qloo's nearest entities as candidates for the writer to pick from."""
    typed = [h for h in await search(name, etype) if match_quality(name, h["name"]) >= MIN_MATCH]
    if typed:
        ranked = _rank(name, typed)
        q = match_quality(name, ranked[0]["name"])
        if q >= 0.8 or etype != "artist":
            return {"match": ranked[0], "candidates": ranked[:5], "certain": q >= 0.8, "quality": round(q, 2)}
    if etype == "artist":
        # Qloo's hackathon data files many current musicians as person records only (DJ Zinhle, Arjan Dhillon).
        # A person record with the same name stands in when no artist record matches with certainty. Person records
        # hold politicians and athletes too, so the name has to match outright (0.95: exact or the same words).
        people = [h for h in await search(name, "person") if match_quality(name, h["name"]) >= 0.95]
        if people:
            p = _rank(name, people)[0]
            return {"match": {**p, "record": "person"}, "candidates": _rank(name, people)[:5], "certain": True,
                    "quality": round(match_quality(name, p["name"]), 2)}
        if typed:
            return {"match": ranked[0], "candidates": ranked[:5], "certain": False, "quality": round(q, 2)}
    loose = _rank(name, await search(name, None))
    same = [h for h in loose if h.get("type") == etype and match_quality(name, h["name"]) >= MIN_MATCH]
    if same:
        return {"match": same[0], "candidates": loose[:5], "certain": False,
                "quality": round(match_quality(name, same[0]["name"]), 2)}
    # e.g. Wetherspoons: Qloo holds single pubs and no chain brand. One pub scores at the wrong scale.
    return {"match": None, "candidates": loose[:5], "certain": False}


# ---------- heatmap profile ----------

async def profile(entity_id: str, cities: list[dict], age: str | None = None) -> dict:
    """Cells and affinity per city for one entity over the room polygon."""
    poly = _polygon(cities)

    async def run():
        try:
            body = await qloo.get("/v2/insights", {
                "filter.type": "urn:heatmap",
                "filter.location": poly,
                "signal.interests.entities": entity_id,
                "signal.demographics.age": age,
                "take": 50,
            })
        except QlooError as e:
            # Some entities carry no geo data at all; Qloo answers 400 for those. Same as an empty map.
            if e.status == 400 and "valid entity" in str(e):
                body = {}
            else:
                raise
        cells = ((body or {}).get("results") or {}).get("heatmap") or []
        return aggregate(cells, cities)

    return await cached(Cache.key("profile", entity_id, poly, age), run)


def aggregate(cells: list, cities: list[dict]) -> dict:
    """Per-city cells, median affinity (Loved), p75, median affinity_rank and popularity, from raw heatmap cells.
    Qloo documents three per-cell measures: affinity (against other entities in the cell),
    affinity_rank (against the entity itself across places) and popularity (signal density)."""
    per: dict[str, dict[str, list[float]]] = {}
    for x in cells:
        loc, q = x.get("location") or {}, x.get("query") or {}
        owner = _owner(loc.get("latitude", 0), loc.get("longitude", 0), cities)
        if owner and q.get("affinity") is not None:
            d = per.setdefault(owner, {"a": [], "r": [], "p": []})
            d["a"].append(q["affinity"])
            if q.get("affinity_rank") is not None:
                d["r"].append(q["affinity_rank"])
            if q.get("popularity") is not None:
                d["p"].append(q["popularity"])
    med = lambda v: round(statistics.median(v), 4) if v else None
    out = {}
    for c in cities:
        d = per.get(c["name"], {"a": [], "r": [], "p": []})
        out[c["name"]] = {
            "cells": len(d["a"]),
            "median": med(d["a"]),
            "p75": round(statistics.quantiles(d["a"], n=4)[2], 4) if len(d["a"]) >= 4 else None,
            "rank": med(d["r"]),
            "popularity": med(d["p"]),
        }
    return {"cities": out, "total": len(cells)}


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


async def recognition(entity: dict, etype: str, cities: list[dict], age: str | None) -> dict:
    """Gemini's estimate of how much of each city recognises the entity. Memory is good at fame."""
    names = [c["name"] for c in cities]

    async def run():
        g = await llm.guess_room([{"id": "x", "name": entity.get("name") or "", "type": etype}], names, age,
                                 model=llm.SWAP_MODEL)
        return {c: v["known"] for c, v in (g.get("x") or {}).items()}

    try:
        return await cached(Cache.key("recog", entity["entity_id"], names, age, llm.SWAP_MODEL), run)
    except Exception as e:  # the map alone still scores
        print(f"recognition failed for {entity.get('name')}: {e}")
        return {}


async def score(entity: dict, etype: str, names: list[str], age: str | None = None) -> dict:
    """Known: Gemini's recognition, raised where Qloo measures a local fan base.
    Loved: Qloo's median affinity in the city, from the age-filtered map when an age band is set."""
    cities = await room(names)
    base_id = await baseline_id(etype)
    calls = [profile(entity["entity_id"], cities), profile(base_id, cities), recognition(entity, etype, cities, age)]
    if age:
        calls.append(profile(entity["entity_id"], cities, age))
    results = await asyncio.gather(*calls)
    prof, base, recog = results[0], results[1], results[2]
    aged = results[3] if age else None

    wanted = list(dict.fromkeys(c["name"] for c in await asyncio.gather(*[city(n) for n in names])))
    mapped = prof["total"] > 0
    out = {"entity_id": entity["entity_id"], "mode": "map" if mapped else "memory", "cities": {},
           "elsewhere": None, "age": age}
    pop = entity.get("popularity") or 0
    # Thin artist records can share one cluster map with other artists (Kabza De Small, Khaligraph Jones,
    # Asake and Wizkid share one that peaks in Lagos), so their fan presence only counts with real popularity.
    floor = not (etype == "artist" and pop < 0.5)

    rows = {}
    for c in cities:
        n = c["name"]
        cells = prof["cities"][n]["cells"] if mapped else 0
        bcells = base["cities"][n]["cells"]
        presence = min(1.0, cells / max(bcells, 1))
        gk = recog.get(n)
        if gk is None:
            known = presence if mapped else pop
        else:
            known = max(gk, presence) if floor else gk
        loved = None
        if mapped and cells >= 5:
            loved = aged["cities"][n]["median"] if aged else prof["cities"][n]["median"]
        v = verdict(known, loved, pop)
        rows[n] = {
            "verdict": v,
            "known": round(known, 2),
            "recognition": round(gk, 2) if gk is not None else None,
            "presence": round(presence, 2),
            "ratio": round(cells / max(bcells, 1), 3),
            "affinity_rank": prof["cities"][n].get("rank") if mapped else None,
            "loved": round(loved, 2) if loved is not None else None,
            "confidence": "low" if (bcells < THIN or not mapped) else "high",
            "why": VERDICTS[v],
            "cells": cells,
            "base_cells": bcells,
        }
    for n in wanted:
        out["cities"][n] = rows[n]
    # Where the fans concentrate: median affinity across the room's polygon. The cells ratio saturates
    # and over-credits the data-dense New York and Los Angeles boxes.
    home = max(rows, key=lambda n: (rows[n]["loved"] or 0, rows[n]["ratio"]))
    out["elsewhere"] = {"city": home, **rows[home]}
    return out


# ---------- swaps ----------

def _swap_tags(entity: dict) -> list[str]:
    tags = entity.get("tags") or []
    rank = lambda t: (0 if ":genre:" in (t["id"] or "") else 1 if ":keyword:" in (t["id"] or "") else 2)
    return [t["id"] for t in sorted(tags, key=rank) if t.get("id")][:3]


def _box(c: dict) -> str:
    s, n = round(c["lat"] - c["hh"], 4), round(c["lat"] + c["hh"], 4)
    w, e = round(c["lon"] - c["hw"], 4), round(c["lon"] + c["hw"], 4)
    return f"POLYGON(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"


async def swap_candidates(entity: dict, etype: str, city_name: str, exclude: set | None = None) -> list[dict]:
    # The city's own box as the location signal: a name query resolves "New York" to the state
    # and "Johannesburg" to a single ward.
    c = await city(city_name)
    where = _box(c)
    ftype = TYPES[etype]
    tags = _swap_tags(entity)
    jobs = [qloo.get("/v2/insights", {
        "filter.type": ftype, "signal.interests.entities": entity["entity_id"],
        "signal.location": where, "filter.exclude.entities": entity["entity_id"], "take": 10,
    })]
    if tags:
        jobs.append(qloo.get("/v2/insights", {
            "filter.type": ftype, "filter.tags": ",".join(tags),
            "signal.location": where, "filter.exclude.entities": entity["entity_id"], "take": 12,
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
