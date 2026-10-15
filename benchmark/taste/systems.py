"""Section 6: run the systems. Raw Qloo cells and raw Gemini answers stay private (spike/out/taste/<snap>/).

Usage: python benchmark/taste/systems.py dev|eval <part> [--stub]
  compose   5.4 room-composition check (dev only): group polygon against [A, B] plus anchors, 10 artists
  qloo      step 1: group heatmaps for every candidate (coverage, clusters, E9), Beyonce per group, the N4 panel
  pairs     step 2: per-pair heatmaps for every covered item in a scored population, Beyonce per city pair
  gemini    S3 (one GUESS call per artist) and S4 (four ranking calls per artist)
  extra     E10 and E11, after the confirmatory run
--stub writes deterministic fake answers with no API calls, for the dry run (11).
"""

import asyncio
import datetime as dt
import hashlib
import json
import os
import random
import sys

from common import (DATA, GEMINI, GEMINI_ALT, GROUPS, PRIVATE, ROOT, TOP100, WITHIN, dump, label, load, preset,
                    sha_order)

SNAP, PART = sys.argv[1], sys.argv[2]
STUB = "--stub" in sys.argv
OUT = PRIVATE / SNAP / ("stub" if STUB else "run")
OUT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("ROOM_DISK_CACHE", str(PRIVATE / "qloo_search_cache"))
os.environ.setdefault("QLOO_CONCURRENCY", "4")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "helenia-11f98")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import engine  # noqa: E402
import llm  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from qloo import QlooError, qloo  # noqa: E402


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def group_cities(snap_items: dict, g: str) -> list[str]:
    """Cities that survived the date rule, in the group's fixed order."""
    live = {i["gold"] for i in snap_items["items"] if i["group"] == g} | {i["other"] for i in snap_items["items"] if i["group"] == g}
    return [c for c in GROUPS[g] if c in live]


# ---------- Qloo ----------

async def heatmap(entity_id: str, cities: list[str], tag: str) -> dict:
    """One heatmap with engine.profile's exact parameters. Every cell is stored; aggregates use engine.aggregate."""
    path = OUT / "heatmaps" / f"{tag}.json"
    if path.exists():
        return load(path)
    room = await engine.room([preset(c) for c in cities])
    poly = engine._polygon(room)
    params = {"filter.type": "urn:heatmap", "filter.location": poly, "signal.interests.entities": entity_id, "take": 50}
    if STUB:
        rnd = random.Random(sha_order(entity_id, tag))
        cells = []
        for c in room:
            for _ in range(rnd.randint(0, 12)):
                cells.append({"location": {"latitude": c["lat"] + rnd.uniform(-c["hh"], c["hh"]),
                                           "longitude": c["lon"] + rnd.uniform(-c["hw"], c["hw"]),
                                           "geohash": "stub"},
                              "query": {"affinity": rnd.random(), "affinity_rank": rnd.random(), "popularity": rnd.random()}})
        body = {"results": {"heatmap": cells}}
    else:
        try:
            body = await qloo.get("/v2/insights", params)
        except QlooError as e:
            if e.status == 400 and "valid entity" in str(e):
                body = {}
            else:
                raise
    cells = ((body or {}).get("results") or {}).get("heatmap") or []
    rec = {"entity_id": entity_id, "params": params, "room": room, "fetched_at": now(), "cells": cells,
           "geohash_lengths": sorted({len((x.get("location") or {}).get("geohash") or "") for x in cells}),
           "total": len(cells), "aggregate": engine.aggregate(cells, room)}
    dump(path, rec)
    return rec


async def run_qloo(items: dict, res: dict, identity: dict):
    """Step 1 (5.3, 5.6, N4): one heatmap per candidate artist over its group polygon, which decides coverage and
    feeds clustering and E9; the Beyonce map per group polygon; the N4 panel on group polygons."""
    groups = [g for g in GROUPS if any(i["group"] == g for i in items["items"])]
    jobs = []
    for g in groups:
        cities = group_cities(items, g)
        ids = sorted({i["artist_id"] for i in items["items"] if i["group"] == g})
        for aid in ids:
            r = res.get(aid) or {}
            if r.get("certain") and identity.get(aid) == "pass":
                jobs.append(heatmap(r["entity_id"], cities, f"grp_{g}_{aid}"))
    bey = await engine.baseline_id("artist")
    for g in groups:
        jobs.append(heatmap(bey, group_cities(items, g), f"basegrp_{g}"))
    print(f"qloo: {len(jobs)} group heatmaps")
    await gather_progress(jobs)
    snap = load(DATA / ("charts_dev_20261015.json" if SNAP == "dev" else "charts_eval.json"))
    panel_jobs, panel = [], {}
    for g in [g for g in WITHIN if g in groups]:
        cc = TOP100[g][0]
        on_city = {x.get("apple_id") for c in GROUPS[g] if c in snap["apple_city"]
                   for e in snap["apple_city"][c]["entries"] for x in e["credits"]}
        names = []
        for e in snap["apple_country"][cc]["entries"]:
            ld = next((x for x in e["credits"] if x.get("apple_id")), None)
            if ld and ld["apple_id"] not in on_city and ld["apple_id"] not in {n[0] for n in names}:
                names.append((ld["apple_id"], ld["name"]))
        hits = await asyncio.gather(*[engine.resolve(n, "artist") for _, n in names])
        chosen = [(aid, n, h["match"]["entity_id"]) for (aid, n), h in zip(names, hits) if h.get("certain")][:50]
        panel[g] = [{"artist_id": a, "artist": n, "entity_id": eid} for a, n, eid in chosen]
        panel_jobs += [heatmap(eid, group_cities(items, g), f"n4_{g}_{aid}") for aid, _, eid in chosen]
    dump(OUT / "n4_panel.json", panel)
    print(f"qloo: {len(panel_jobs)} N4 panel heatmaps")
    await gather_progress(panel_jobs)


async def run_pairs(items: dict, res: dict, identity: dict):
    """Step 2 (5.4: per-pair rooms are primary): one heatmap per scored item over [A, B] plus the anchors, and one
    Beyonce map per city pair. Only items in a scored population need one."""
    import score
    covered = score.covered_set(items["items"], res, identity, lambda g, a: score.heat_at(OUT, f"grp_{g}_{a}"))
    pops = score.populations([dict(i, covered=(i["group"], i["artist_id"]) in covered) for i in items["items"]])
    need = {}
    for name, pop in pops.items():
        for it in pop:
            if it["covered"]:
                need[(it["group"], it["artist_id"], *sorted([it["gold"], it["other"]]))] = it
    jobs = [heatmap(res[aid]["entity_id"], [a, b], f"pair_{g}_{aid}_{a}_{b}") for (g, aid, a, b) in sorted(need)]
    bey = await engine.baseline_id("artist")
    pairs = sorted({(g, a, b) for (g, _, a, b) in need})
    jobs += [heatmap(bey, [a, b], f"basepair_{g}_{a}_{b}") for (g, a, b) in pairs]
    dump(OUT / "pairs_plan.json", {"items": len(need), "city_pairs": len(pairs),
                                   "populations": {k: len(v) for k, v in pops.items()}})
    print(f"qloo: {len(need)} per-pair heatmaps, {len(pairs)} pair baselines")
    await gather_progress(jobs)


async def gather_progress(jobs):
    done = 0
    async def wrap(j):
        nonlocal done
        try:
            return await j
        finally:
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
    return await asyncio.gather(*[wrap(j) for j in jobs], return_exceptions=True)


async def compose_check(items: dict, res: dict):
    """5.4: does a cell's affinity_rank depend on the room? 10 artists by sha1, 3 pairs each."""
    by_artist = {}
    for it in items["items"]:
        if it["group"] in WITHIN and (res.get(it["artist_id"]) or {}).get("certain"):
            by_artist.setdefault((it["group"], it["artist_id"]), []).append(it)
    picks = sorted(by_artist, key=lambda k: sha_order("compose", *k))[:10]
    report = []
    for g, aid in picks:
        eid = res[aid]["entity_id"]
        whole = await heatmap(eid, group_cities(items, g), f"compose_group_{g}_{aid}")
        pairs = sorted(by_artist[(g, aid)], key=lambda i: sha_order("compose", aid, i["gold"], i["other"]))[:3]
        for it in pairs:
            two = await heatmap(eid, sorted([it["gold"], it["other"]]), f"compose_pair_{g}_{aid}_{it['gold']}_{it['other']}")
            def cells_in(rec, cities):
                keep = {preset(c) for c in cities}
                out = {}
                for x in rec["cells"]:
                    loc = x.get("location") or {}
                    o = engine._owner(loc.get("latitude", 0), loc.get("longitude", 0), rec["room"])
                    if o in keep:
                        out[loc.get("geohash")] = (x.get("query") or {}).get("affinity_rank")
                return out
            a, b = cells_in(whole, [it["gold"], it["other"]]), cells_in(two, [it["gold"], it["other"]])
            same = set(a) & set(b)
            report.append({"group": g, "artist_id": aid, "pair": [it["gold"], it["other"]],
                           "cells_group_room": len(a), "cells_pair_room": len(b), "shared_cells": len(same),
                           "rank_identical": all(a[k] == b[k] for k in same) and set(a) == set(b),
                           "geohash_len_group": whole["geohash_lengths"], "geohash_len_pair": two["geohash_lengths"]})
    verdict = all(r["rank_identical"] and r["geohash_len_group"] == r["geohash_len_pair"] for r in report)
    dump(OUT / "compose_check.json", {"identical": verdict, "rows": report})
    print(f"compose check: identical={verdict} over {len(report)} pairs")


# ---------- Gemini ----------

class Rank(BaseModel):
    city: str
    rank: int


class Ranking(BaseModel):
    known: bool
    genre: str
    ranking: list[Rank]


S4_PROMPT = """You know popular music around the world. Answer from your own knowledge only.
ARTIST: {credit}
APPLE MUSIC GENRE: {genre}
CITIES IN {country}: {cities}
First, say whether you know this artist (known: true or false) and name their main genre in a few words.
Then rank every city from 1 to {k} by how strongly listeners in that city favour this artist compared with other artists, 1 being strongest. Use each rank once and copy each city exactly as written."""

E10_LINE = ("Then rank every city from 1 to {k} by how strongly listeners in that city favour this artist compared "
            "with other artists, 1 being strongest.")
E10_NEW = ("Then rank every city from 1 to {k} by how strongly listeners in that city favour this artist right now, "
           "on Apple Music, compared with other artists, 1 being strongest.")


def call(prompt: str, schema, model: str):
    """llm._call's request, with no race, no tools and no grounding; returns ids for the log."""
    from google.genai import types
    cfg = types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json", response_schema=schema,
                                      http_options=types.HttpOptions(timeout=60_000))
    assert not cfg.tools, "no tools or grounding"
    r = llm.client().models.generate_content(model=model, contents=prompt, config=cfg)
    return r.parsed, getattr(r, "response_id", None), getattr(r, "model_version", None)


def match_city(answer: str, labels: list[str]) -> str | None:
    a = answer.strip().lower()
    for lb in labels:
        if a == lb.lower() or a == lb.split(",")[0].strip().lower():
            return lb
    return None


async def ask(sem, system, key, prompt, schema, model, labels, parse):
    """Up to 5 attempts on the same model; a missing city counts as a transport failure."""
    async with sem:
        last = None
        for attempt in range(5):
            try:
                if STUB:
                    rnd = random.Random(sha_order(system, *key))
                    parsed = parse_stub(schema, labels, rnd)
                    rid, mv = "stub", "stub"
                else:
                    parsed, rid, mv = await asyncio.to_thread(call, prompt, schema, model)
                out = parse(parsed, labels)
                if out is not None:
                    return {"system": system, "key": list(key), "model": model, "response_id": rid, "model_version": mv,
                            "attempts": attempt + 1, "at": now(), "out": out,
                            "prompt_sha": hashlib.sha1(prompt.encode()).hexdigest()}
                last = "missing city"
            except Exception as e:
                last = repr(e)[:200]
            await asyncio.sleep(2 * (attempt + 1))
        return {"system": system, "key": list(key), "model": model, "failed": last, "at": now()}


def parse_stub(schema, labels, rnd):
    if schema is llm.RoomGuess:
        return llm.RoomGuess(references=[llm.RefGuess(id="x", cities=[
            llm.CityGuess(city=lb, known=rnd.random(), loved=rnd.random()) for lb in labels])])
    order = labels[:]
    rnd.shuffle(order)
    return Ranking(known=rnd.random() > 0.3, genre="stub", ranking=[Rank(city=lb, rank=i + 1) for i, lb in enumerate(order)])


def parse_guess(parsed, labels):
    refs = parsed.references if parsed else []
    if not refs:
        return None
    got = {}
    for c in refs[0].cities:
        lb = match_city(c.city, labels)
        if lb:
            got[lb] = {"known": max(0.0, min(1.0, c.known)), "loved": max(0.0, min(1.0, c.loved))}
    return got if set(got) == set(labels) else None


def parse_rank(parsed, labels):
    if not parsed:
        return None
    got = {}
    for r in parsed.ranking:
        lb = match_city(r.city, labels)
        if lb:
            got[lb] = r.rank
    if set(got) != set(labels):
        return None
    return {"known": parsed.known, "genre": parsed.genre, "rank": got}


async def run_gemini(items: dict, extra: bool):
    sem = asyncio.Semaphore(8)
    jobs = []
    artists = {}
    for it in items["items"]:
        artists.setdefault((it["group"], it["artist_id"]), it)
    for (g, aid), it in sorted(artists.items()):
        cities = sorted(group_cities(items, g))
        labels = [label(c) for c in cities]
        genre = it.get("genre") or "unknown"
        country = {"us": "the United States", "gb": "the United Kingdom", "ca": "Canada", "za": "South Africa",
                   "in": "India", "africa": "Africa"}[g]
        if not extra:
            row = f"x | {it['artist']} | artist ({genre})" if it.get("genre") else f"x | {it['artist']} | artist"
            p3 = llm.GUESS.format(age="", cities=", ".join(labels), rows=row)
            jobs.append(ask(sem, "S3", (g, aid), p3, llm.RoomGuess, GEMINI, labels, parse_guess))
            for run, order in enumerate(["alpha", "alpha", "reverse", "reverse"]):
                ls = labels if order == "alpha" else labels[::-1]
                p4 = S4_PROMPT.format(credit=it["artist"], genre=genre, country=country, cities=", ".join(ls), k=len(ls))
                jobs.append(ask(sem, "S4", (g, aid, run, order), p4, Ranking, GEMINI, labels, parse_rank))
        else:
            p10 = S4_PROMPT.format(credit=it["artist"], genre=genre, country=country, cities=", ".join(labels),
                                   k=len(labels)).replace(E10_LINE.format(k=len(labels)), E10_NEW.format(k=len(labels)))
            jobs.append(ask(sem, "E10", (g, aid, 0, "alpha"), p10, Ranking, GEMINI, labels, parse_rank))
            for run, order in enumerate(["alpha", "alpha", "reverse", "reverse"]):
                ls = labels if order == "alpha" else labels[::-1]
                p11 = S4_PROMPT.format(credit=it["artist"], genre=genre, country=country, cities=", ".join(ls), k=len(ls))
                jobs.append(ask(sem, "E11", (g, aid, run, order), p11, Ranking, GEMINI_ALT, labels, parse_rank))
    print(f"gemini: {len(jobs)} calls")
    rows = await gather_progress(jobs)
    name = "gemini_extra.jsonl" if extra else "gemini.jsonl"
    with open(OUT / name, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r if isinstance(r, dict) else {"failed": repr(r)[:200]}, ensure_ascii=False) + "\n")
    print(f"gemini: {sum(1 for r in rows if isinstance(r, dict) and 'out' in r)} answered, "
          f"{sum(1 for r in rows if not isinstance(r, dict) or 'failed' in r)} failed")


# ---------- 3.2 box check ----------

COUNTRY_BOX = {"United States": (18, 50, -161, -66), "United Kingdom": (49.8, 60.9, -8.7, 1.8),
               "Canada": (41.6, 83, -141, -52), "South Africa": (-35, -22, 16.3, 33), "India": (6.5, 35.7, 68, 97.5),
               "Nigeria": (4, 14, 2.7, 14.7), "Ghana": (4.7, 11.2, -3.3, 1.2), "Kenya": (-4.7, 5, 33.9, 41.9)}


def box_check():
    from common import CITY_COUNTRY
    rows = []
    for g, cities in GROUPS.items():
        for c in cities:
            k = preset(c)
            assert k in engine.PRESET, f"{c} would fall through to Qloo search"
            lat, lon, hh, hw = engine.PRESET[k]
            s, n, w, e = COUNTRY_BOX[CITY_COUNTRY[c]]
            assert s <= lat <= n and w <= lon <= e, f"{c} centre lies outside {CITY_COUNTRY[c]}"
            rows.append({"group": g, "city": c, "preset": k, "lat": lat, "lon": lon, "half_h": hh, "half_w": hw})
            print(f"  {g:7} {c:16} {lat:8.2f} {lon:9.2f}  +/-{hh:.2f} x {hw:.2f}")
    dump(DATA / "boxes.json", rows)
    print(f"boxes: {len(rows)} ok")


def main():
    if PART == "boxes":
        box_check()
        return
    items = load(DATA / f"items_{SNAP}.json")
    res = load(PRIVATE / SNAP / "resolution.json") if (PRIVATE / SNAP / "resolution.json").exists() else {}
    idp = DATA / f"identity_{SNAP}.json"
    identity = load(idp)["verdicts"] if idp.exists() else {a: "pass" for a in res}  # dev dry run: no check yet
    if PART == "compose":
        asyncio.run(compose_check(items, res))
    elif PART == "qloo":
        asyncio.run(run_qloo(items, res, identity))
    elif PART == "pairs":
        asyncio.run(run_pairs(items, res, identity))
    elif PART == "gemini":
        asyncio.run(run_gemini(items, extra=False))
    elif PART == "extra":
        asyncio.run(run_gemini(items, extra=True))


if __name__ == "__main__":
    main()
