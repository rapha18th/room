"""The Fame track: which of ten cities is each reference best known in?

56 references with one unambiguous home city each. This is the question Room hands to Gemini (who
recognises a name), so the track measures Room's division of labour as much as any single system.

Systems
  qloo_cells   Qloo heatmap fan presence: cells in the city against a household name of the same type
  qloo_taste   Qloo heatmap median affinity in the city, the measure Qloo documents
  llm          Gemini alone, guessing from memory in batches
  room         Room as shipped: Gemini recognition, raised by Qloo fan presence where the record is solid

Reported on all references, on a clean subset (names that carry their home city, state or country are
removed, since they hand any system the answer), and by region (US, Canada, UK against Africa and India,
where Qloo holds roughly a quarter of the signal density). References Qloo cannot resolve with certainty
are counted as coverage gaps, apart from accuracy.

Usage: python benchmark/run.py   (needs QLOO_API_KEY and Vertex credentials, as for the service)
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "service"))
os.environ.setdefault("ROOM_DISK_CACHE", str(HERE.parent / ".cache"))
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parent / ".env")

import engine  # noqa: E402
import llm  # noqa: E402

SPEC = json.loads((HERE / "references.json").read_text(encoding="utf-8"))
CITIES = SPEC["cities"]
SYSTEMS = ("qloo_cells", "qloo_taste", "llm", "room")
NAMES = {"qloo_cells": "Qloo fan presence alone", "qloo_taste": "Qloo taste (median affinity) alone",
         "llm": "Gemini alone, from memory", "room": "Room"}
GIVEAWAY = {"New York": ["new york"], "Los Angeles": ["los angeles"], "Dallas": ["dallas", "texas"],
            "Atlanta": ["atlanta"], "Toronto": ["toronto"], "London": ["london"], "Johannesburg": ["johannesburg"],
            "Lagos": ["lagos", "naija"], "Nairobi": ["nairobi", "kenya"], "Mumbai": ["mumbai", "india"]}
WESTERN = {"New York", "Los Angeles", "Dallas", "Atlanta", "Toronto", "London"}


def giveaway(r) -> bool:
    return any(w in r["name"].lower() for w in GIVEAWAY.get(r["home"], []))


async def resolve_all():
    out, dropped = [], []
    for i, r in enumerate(SPEC["references"]):
        m = await engine.resolve(r["name"], r["type"])
        if m["match"] and m["certain"]:
            out.append({**r, "id": f"b{i}", "match": m["match"]})
        else:
            dropped.append(r["name"])
    return out, dropped


async def room_scores(refs):
    sem = asyncio.Semaphore(3)

    async def one(r):
        async with sem:
            return r["id"], await engine.score(r["match"], r["type"], CITIES)

    return dict(await asyncio.gather(*[one(r) for r in refs]))


async def llm_scores(refs):
    out = {}
    for i in range(0, len(refs), 12):
        batch = refs[i:i + 12]
        out.update(await llm.guess_room([{"id": r["id"], "name": r["match"]["name"], "type": r["type"]}
                                         for r in batch], CITIES))
    return out


def top(values: dict):
    vals = {c: v for c, v in values.items() if v is not None}
    return max(vals, key=lambda c: vals[c]) if vals else None


def tops_for(r, s, g):
    rows = s["cities"]
    mapped = s["mode"] == "map"
    return {
        "qloo_cells": top({c: v["ratio"] for c, v in rows.items()}) if mapped else None,
        "qloo_taste": top({c: v["loved"] for c, v in rows.items()}) if mapped else None,
        "llm": top({c: g.get(c, {}).get("known") for c in CITIES}),
        "room": top({c: (v["known"], v["loved"] or 0) for c, v in rows.items()}),
    }


def rate(rows, key):
    if not rows:
        return None
    return round(sum(r["tops"][key] == r["home"] for r in rows) / len(rows), 3)


async def main():
    t = time.time()
    refs, dropped = await resolve_all()
    print(f"{len(refs)} resolved with certainty; coverage gaps: {dropped}")
    room = await room_scores(refs)
    guess = await llm_scores(refs)

    rows = []
    for r in refs:
        tops = tops_for(r, room[r["id"]], guess.get(r["id"], {}))
        rows.append({"name": r["name"], "type": r["type"], "home": r["home"], "giveaway": giveaway(r),
                     "mode": room[r["id"]]["mode"], "tops": tops})

    subsets = {
        "all": rows,
        "clean": [x for x in rows if not x["giveaway"]],
        "us_canada_uk": [x for x in rows if x["home"] in WESTERN],
        "africa_india": [x for x in rows if x["home"] not in WESTERN],
        "clean_artists": [x for x in rows if not x["giveaway"] and x["type"] == "artist"],
        "clean_brands": [x for x in rows if not x["giveaway"] and x["type"] == "brand"],
    }
    table = {k: {"n": len(v), **{s: rate(v, s) for s in SYSTEMS}} for k, v in subsets.items()}
    result = {"cities": CITIES, "resolved": len(refs), "coverage_gaps": dropped, "table": table,
              "rows": rows, "seconds": round(time.time() - t)}
    (HERE / "results.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    lines = [f"Fame track: home city found. {len(refs)} references resolved with certainty out of "
             f"{len(SPEC['references'])}; coverage gaps: {', '.join(dropped) or 'none'}.", "",
             "| Subset | n | " + " | ".join(NAMES[s] for s in SYSTEMS) + " |",
             "|---|---|" + "---|" * len(SYSTEMS)]
    for k, v in table.items():
        lines.append(f"| {k.replace('_', ' ')} | {v['n']} | " + " | ".join(pct(v[s]) for s in SYSTEMS) + " |")
    lines += ["", "| Reference | Home | " + " | ".join(NAMES[s] for s in SYSTEMS) + " |",
              "|---|---|" + "---|" * len(SYSTEMS)]
    for x in rows:
        mark = lambda c: f"**{c}**" if c == x["home"] else (c or "no map")
        lines.append(f"| {x['name']}{' *' if x['giveaway'] else ''} | {x['home']} | "
                     + " | ".join(mark(x["tops"][s]) for s in SYSTEMS) + " |")
    lines.append("")
    lines.append("\\* name carries its home city, state or country; left out of the clean subset.")
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(table, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
