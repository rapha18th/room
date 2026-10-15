"""Room API spike: can Qloo tell us whether a cultural reference lands with an audience?

Five tests against the hackathon API:
  A  resolve   /search turns reference text into the right entity
  B  place     /v2/insights affinity for known references, per city
  C  heatmap   /v2/insights urn:heatmap, per locality inside a country
  D  age       /v2/insights urn:demographics, age skew per reference
  E  age+place does signal.demographics.age move affinity inside a city
  F  swaps     local equivalents for a reference in a foreign city
  G  known     known-but-mocked references: popularity vs affinity
  H  coverage  how much data sits behind each market, Harare included
  I  trending  is /v2/trending open on the hackathon host

Usage:
  python spike.py            # live run, needs QLOO_API_KEY in env or ../.env
  python spike.py --dry-run  # print the planned requests only
"""

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
OUT = HERE / "out"
RAW = OUT / "raw"
BASE = os.environ.get("QLOO_BASE", "https://hackathon.api.qloo.com")
DRY = "--dry-run" in sys.argv

CITIES = ["Dallas", "Philadelphia", "Los Angeles", "Atlanta", "Toronto", "London", "Johannesburg", "Lagos"]

# (reference text, entity type, city where it should land hardest)
REFS = [
    ("Whataburger", "urn:entity:brand", "Dallas"),
    ("Wawa", "urn:entity:brand", "Philadelphia"),
    ("In-N-Out Burger", "urn:entity:brand", "Los Angeles"),
    ("Waffle House", "urn:entity:brand", "Atlanta"),
    ("Tim Hortons", "urn:entity:brand", "Toronto"),
    ("Greggs", "urn:entity:brand", "London"),
    ("Chicken Licken", "urn:entity:brand", "Johannesburg"),
    ("Kabza De Small", "urn:entity:artist", "Johannesburg"),
    ("Burna Boy", "urn:entity:artist", "Lagos"),
    ("Morgan Wallen", "urn:entity:artist", "Dallas"),
    ("Drake", "urn:entity:artist", "Toronto"),
    ("Coronation Street", "urn:entity:tv_show", "London"),
    ("Skeem Saam", "urn:entity:tv_show", "Johannesburg"),
    ("Atlanta", "urn:entity:tv_show", "Atlanta"),
]

AGES = ["24_and_younger", "55_and_older"]

calls = []


def load_key():
    key = os.environ.get("QLOO_API_KEY")
    env = HERE.parent / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("QLOO_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key


KEY = load_key()


def get(path, params, tag):
    """GET with cache, retry on 429, latency log. Returns parsed JSON or None."""
    cache = RAW / (re.sub(r'[<>:"/\\|?*]', "_", tag) + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if DRY:
        print(f"[dry] {tag}: GET {path} {params}")
        return None
    for attempt in range(4):
        t0 = time.time()
        r = requests.get(BASE + path, params=params, headers={"X-Api-Key": KEY}, timeout=30)
        ms = int((time.time() - t0) * 1000)
        calls.append({"tag": tag, "status": r.status_code, "ms": ms})
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        break
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text[:500]}
    body["_status"] = r.status_code
    body["_url"] = r.url
    cache.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.15)
    return body


def entities(body):
    res = (body or {}).get("results")
    if isinstance(res, dict):
        return res.get("entities") or []
    return res or []


def affinity(e):
    return (e.get("query") or {}).get("affinity")


# ---------- A: resolve ----------
def test_resolve():
    out = {}
    for text, etype, _ in REFS:
        body = get("/search", {"query": text, "types": etype, "take": 3}, f"A_search_{text}")
        hits = entities(body)
        if not hits and body is not None:
            body = get("/search", {"query": text, "take": 3}, f"A_search_any_{text}")
            hits = entities(body)
        out[text] = hits[0] if hits else None
    return out


# ---------- B: affinity per city ----------
def test_place(resolved):
    by_type = {}
    for text, etype, _ in REFS:
        if resolved.get(text):
            by_type.setdefault(etype, []).append(text)
    matrix = {text: {} for text, _, _ in REFS}
    for etype, texts in by_type.items():
        ids = ",".join(resolved[t]["entity_id"] for t in texts)
        id_to_text = {resolved[t]["entity_id"]: t for t in texts}
        for city in CITIES:
            body = get(
                "/v2/insights",
                {"filter.type": etype, "signal.location.query": city, "filter.results.entities": ids, "take": len(texts)},
                f"B_{etype.split(':')[-1]}_{city}",
            )
            for e in entities(body):
                t = id_to_text.get(e.get("entity_id"))
                if t:
                    matrix[t][city] = affinity(e)
    return matrix


def score_place(matrix):
    """Expected city wins its row? Raw, and after removing each city's baseline."""
    col_mean = {}
    for c in CITIES:
        vals = [row[c] for row in matrix.values() if row.get(c) is not None]
        col_mean[c] = statistics.mean(vals) if vals else 0
    rows = []
    for text, _, want in REFS:
        row = matrix.get(text) or {}
        full = {c: v for c, v in row.items() if v is not None}
        if not full:
            rows.append((text, want, None, None, "no data"))
            continue
        raw_top = max(full, key=full.get)
        adj = {c: v - col_mean[c] for c, v in full.items()}
        adj_top = max(adj, key=adj.get)
        rows.append((text, want, raw_top, adj_top, ""))
    return rows, col_mean


# ---------- C: heatmap by locality ----------
def test_heatmap(resolved):
    probes = [("Whataburger", "United States"), ("Wawa", "United States"), ("Chicken Licken", "South Africa"), ("Greggs", "United Kingdom")]
    out = {}
    for text, region in probes:
        hit = resolved.get(text)
        if not hit:
            continue
        for boundary in ["urn:entity:locality", None]:
            p = {"filter.type": "urn:heatmap", "filter.location.query": region,
                 "signal.interests.entities": hit["entity_id"], "take": 25}
            if boundary:
                p["output.heatmap.boundary"] = boundary
            body = get("/v2/insights", p, f"C_heatmap_{text}_{boundary or 'geohash'}")
            hm = ((body or {}).get("results") or {}).get("heatmap") or []
            out[f"{text} / {region} / {boundary or 'geohash'}"] = hm[:8]
    return out


# ---------- D: demographics ----------
def test_age(resolved):
    out = {}
    for text, _, _ in REFS:
        hit = resolved.get(text)
        if not hit:
            continue
        body = get("/v2/insights", {"filter.type": "urn:demographics", "signal.interests.entities": hit["entity_id"]}, f"D_demo_{text}")
        demo = ((body or {}).get("results") or {}).get("demographics") or []
        out[text] = (demo[0].get("query") or {}).get("age") if demo else None
    return out


# ---------- E: age inside a city ----------
def test_age_in_city(resolved):
    texts = [t for t, e, _ in REFS if e == "urn:entity:artist" and resolved.get(t)]
    ids = ",".join(resolved[t]["entity_id"] for t in texts)
    id_to_text = {resolved[t]["entity_id"]: t for t in texts}
    out = {t: {} for t in texts}
    for age in AGES:
        body = get("/v2/insights", {"filter.type": "urn:entity:artist", "signal.location.query": "Atlanta",
                                    "signal.demographics.age": age, "filter.results.entities": ids, "take": len(texts)},
                   f"E_artist_Atlanta_{age}")
        for e in entities(body):
            t = id_to_text.get(e.get("entity_id"))
            if t:
                out[t][age] = affinity(e)
    return out


# ---------- F: swaps ----------
SWAPS = [("Waffle House", "London"), ("Wawa", "Johannesburg"), ("Greggs", "Atlanta"),
         ("Chicken Licken", "Dallas"), ("Coronation Street", "Lagos"), ("Morgan Wallen", "Johannesburg")]


def test_swaps(resolved):
    etype = {t: e for t, e, _ in REFS}
    out = {}
    for text, city in SWAPS:
        hit = resolved.get(text)
        if not hit:
            continue
        # F1: "like this, loved here"
        b1 = get("/v2/insights", {"filter.type": etype[text], "signal.interests.entities": hit["entity_id"],
                                  "signal.location.query": city, "filter.exclude.entities": hit["entity_id"], "take": 5},
                 f"F1_{text}_{city}")
        # F2: same tags, loved here
        tags = [t.get("tag_id") or t.get("id") for t in (hit.get("tags") or [])][:3]
        tags = [t for t in tags if t]
        b2 = None
        if tags:
            b2 = get("/v2/insights", {"filter.type": etype[text], "filter.tags": ",".join(tags),
                                      "signal.location.query": city, "take": 5}, f"F2_{text}_{city}")
        out[f"{text} -> {city}"] = {
            "like_this_here": [(e.get("name"), affinity(e)) for e in entities(b1)],
            "same_tags_here": [(e.get("name"), affinity(e)) for e in entities(b2)],
            "tags_used": tags,
        }
    return out


# ---------- G: known vs loved ----------
# References everyone knows and many mock. A joke needs recognition; Qloo scores affinity.
KNOWN_MOCKED = [("Nickelback", "urn:entity:artist"), ("Crocs", "urn:entity:brand"), ("Nickelodeon", "urn:entity:brand")]


def test_known_vs_loved():
    out = {}
    for text, etype in KNOWN_MOCKED:
        body = get("/search", {"query": text, "types": etype, "take": 1}, f"G_search_{text}")
        hits = entities(body)
        if not hits:
            continue
        hit = hits[0]
        row = {"popularity": hit.get("popularity")}
        for city in ["Dallas", "London"]:
            b = get("/v2/insights", {"filter.type": etype, "signal.location.query": city,
                                     "filter.results.entities": hit["entity_id"], "take": 1}, f"G_{text}_{city}")
            es = entities(b)
            row[city] = affinity(es[0]) if es else None
        out[text] = row
    return out


# ---------- H: coverage per market ----------
def test_coverage():
    """How much data sits behind each city? Count results and spread for one generic query."""
    out = {}
    for city in ["Dallas", "London", "Johannesburg", "Lagos", "Harare"]:
        b = get("/v2/insights", {"filter.type": "urn:entity:place", "signal.location.query": city, "take": 50},
                f"H_places_{city}")
        es = entities(b)
        pops = [e.get("popularity") for e in es if e.get("popularity") is not None]
        out[city] = {"places": len(es), "median_pop": statistics.median(pops) if pops else None,
                     "status": (b or {}).get("_status")}
    return out


# ---------- I: trending over time ----------
def test_trending(resolved):
    out = {}
    for text in ["Burna Boy", "Morgan Wallen", "Coronation Street"]:
        hit = resolved.get(text)
        if not hit:
            continue
        etype = {t: e for t, e, _ in REFS}[text]
        b = get("/v2/trending", {"signal.interests.entities": hit["entity_id"], "filter.type": etype,
                                 "filter.start_date": "2025-10-01", "filter.end_date": "2026-10-01", "take": 5},
                f"I_trend_{text}")
        out[text] = {"status": (b or {}).get("_status"), "sample": json.dumps((b or {}).get("results"))[:300]}
    return out


def fmt(v):
    return "-" if v is None else f"{v:.2f}"


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    if not KEY and not DRY:
        sys.exit("No QLOO_API_KEY. Put it in room/.env or the environment, or run with --dry-run.")

    resolved = test_resolve()
    if DRY:
        fake = {t: {"entity_id": f"<{t}>", "tags": []} for t, _, _ in REFS}
        resolved = fake
    matrix = test_place(resolved)
    heat = test_heatmap(resolved)
    age = test_age(resolved)
    age_city = test_age_in_city(resolved)
    swaps = test_swaps(resolved)
    known = test_known_vs_loved()
    coverage = test_coverage()
    trend = test_trending(resolved)
    if DRY:
        print(f"\nDry run planned the requests above. Base: {BASE}")
        return

    L = ["# Room API spike report", "", f"Base: {BASE}", ""]

    L += ["## A. Resolve", "", "| Reference | Top hit | Type | Popularity |", "|---|---|---|---|"]
    for text, _, _ in REFS:
        h = resolved.get(text)
        if h:
            L.append(f"| {text} | {h.get('name')} | {h.get('subtype') or h.get('types')} | {fmt(h.get('popularity'))} |")
        else:
            L.append(f"| {text} | MISS | | |")

    rows, col_mean = score_place(matrix)
    L += ["", "## B. Affinity per city", "", "| Reference | " + " | ".join(CITIES) + " |", "|---" * (len(CITIES) + 1) + "|"]
    for text, _, _ in REFS:
        L.append(f"| {text} | " + " | ".join(fmt(matrix[text].get(c)) for c in CITIES) + " |")
    L.append("| *city mean* | " + " | ".join(fmt(col_mean[c]) for c in CITIES) + " |")
    raw_hits = sum(1 for r in rows if r[2] == r[1])
    adj_hits = sum(1 for r in rows if r[3] == r[1])
    scored = sum(1 for r in rows if r[2])
    L += ["", "| Reference | Expected | Raw top | Baseline-adjusted top |", "|---|---|---|---|"]
    for text, want, raw_top, adj_top, note in rows:
        L.append(f"| {text} | {want} | {raw_top or note} | {adj_top or ''} |")
    L += ["", f"**Raw: {raw_hits}/{scored}. Baseline-adjusted: {adj_hits}/{scored}.** Pass bar: 9 of 14."]

    L += ["", "## C. Heatmap", ""]
    for k, pts in heat.items():
        L.append(f"**{k}**: " + ("; ".join(
            f"{(p.get('location') or {}).get('name') or (p.get('location') or {}).get('geohash')}"
            f" a={fmt((p.get('query') or {}).get('affinity'))}" for p in pts) or "empty"))
        L.append("")

    L += ["## D. Age skew (urn:demographics)", "", "| Reference | " + " | ".join(
        ["24-", "25-29", "30-34", "35-44", "45-54", "55+"]) + " |", "|---" * 7 + "|"]
    keys = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"]
    for text, _, _ in REFS:
        a = age.get(text)
        L.append(f"| {text} | " + (" | ".join(fmt(a.get(k)) for k in keys) if a else "no data") + " |")

    L += ["", "## E. Age inside Atlanta (artists)", "", "| Artist | 24- | 55+ | Delta |", "|---|---|---|---|"]
    for t, v in age_city.items():
        y, o = v.get(AGES[0]), v.get(AGES[1])
        d = fmt(y - o) if y is not None and o is not None else "-"
        L.append(f"| {t} | {fmt(y)} | {fmt(o)} | {d} |")

    L += ["", "## F. Swaps", ""]
    for k, v in swaps.items():
        L.append(f"**{k}** (tags {v['tags_used']})")
        L.append(f"- like this, loved here: {v['like_this_here']}")
        L.append(f"- same tags, loved here: {v['same_tags_here']}")
        L.append("")

    L += ["## G. Known vs loved", "", "| Reference | Global popularity | Dallas affinity | London affinity |", "|---|---|---|---|"]
    for t, v in known.items():
        L.append(f"| {t} | {fmt(v['popularity'])} | {fmt(v.get('Dallas'))} | {fmt(v.get('London'))} |")
    L += ["", "High popularity with low affinity means Qloo sees the reference and the audience dislikes it. "
          "That is the case a joke can use, and the case Room must label.", ""]

    L += ["## H. Coverage per market", "", "| City | Places returned | Median popularity | HTTP |", "|---|---|---|---|"]
    for c, v in coverage.items():
        L.append(f"| {c} | {v['places']} | {fmt(v['median_pop'])} | {v['status']} |")

    L += ["", "## I. Trending", ""]
    for t, v in trend.items():
        L.append(f"- **{t}**: HTTP {v['status']} {v['sample']}")
    L.append("")

    ok = [c for c in calls if c["status"] == 200]
    L += ["## Calls", "", f"{len(calls)} calls, {len(ok)} OK. "
          f"Median latency {statistics.median([c['ms'] for c in ok]) if ok else '-'} ms."]
    bad = [c for c in calls if c["status"] != 200]
    for c in bad:
        L.append(f"- {c['tag']}: HTTP {c['status']}")

    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
