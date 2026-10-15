"""Room against an LLM alone.

Sixty references, each with one home city among ten. Both systems say how well-known each
reference is in every city. A system scores a hit when its top city is the home city.

  Room       one Qloo heatmap per reference over the ten cities; Known per city
  LLM alone  Gemini's own estimate of Known per city, from the same model Room reads with

Also reported: how often each system calls the home city a place the reference dies (a miss
that would mislead a writer), and how often it calls a reference known far from home.

Usage: python benchmark/run.py   (needs QLOO_API_KEY and Vertex credentials, as for the service)
"""

import asyncio
import json
import os
import statistics
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
            s = await engine.score(r["match"], r["type"], CITIES)
            return r["id"], s

    return dict(await asyncio.gather(*[one(r) for r in refs]))


async def llm_scores(refs):
    out = {}
    for i in range(0, len(refs), 12):
        batch = refs[i:i + 12]
        out.update(await llm.guess_room([{"id": r["id"], "name": r["match"]["name"], "type": r["type"]}
                                         for r in batch], CITIES))
    return out


def top(known: dict):
    return max(known, key=lambda c: known[c]) if known else None


def summarise(refs, room, guess):
    """Three systems, one question each: which of the ten cities is this reference's home?

      qloo_map   Qloo heatmap fan presence alone (cells against a household name)
      llm        Gemini alone, guessing from memory in one batch
      room       Room as shipped: Gemini recognition with Qloo fan presence as a floor
    """
    systems = ("qloo_map", "llm", "room")
    hits = {k: 0 for k in systems}
    home_dead = {k: 0 for k in systems}
    rows, disagree = [], []
    for r in refs:
        s = room[r["id"]]
        cities = s["cities"]
        qmap = {c: v["ratio"] for c, v in cities.items()} if s["mode"] == "map" else {}
        roomk = {c: (v["known"], v["ratio"]) for c, v in cities.items()}
        g = guess.get(r["id"], {})
        llmk = {c: g.get(c, {}).get("known", 0.0) for c in CITIES}
        tops = {"qloo_map": top(qmap), "llm": top(llmk),
                "room": max(roomk, key=lambda c: roomk[c]) if roomk else None}
        home_k = {"qloo_map": min(1, qmap.get(r["home"], 0)), "llm": llmk.get(r["home"], 0),
                  "room": roomk.get(r["home"], (0, 0))[0]}
        for k in systems:
            hits[k] += tops[k] == r["home"]
            home_dead[k] += home_k[k] < 0.15
        for c in CITIES:
            q, m = min(1, qmap.get(c, 0)), llmk.get(c, 0)
            if (q >= 0.45) != (m >= 0.45) and abs(q - m) >= 0.3:
                disagree.append({"name": r["name"], "city": c, "qloo_map": round(q, 2), "llm": round(m, 2),
                                 "room": roomk.get(c, (None,))[0]})
        rows.append({"name": r["name"], "home": r["home"], **{f"{k}_top": tops[k] for k in systems},
                     "room_mode": s["mode"]})
    n = len(refs)
    return {
        "n": n,
        "top1": {k: round(v / n, 3) for k, v in hits.items()},
        "home_called_dead": home_dead,
        "rows": rows,
        "disagreements": sorted(disagree, key=lambda d: -abs(d["qloo_map"] - d["llm"])),
    }


async def main():
    t = time.time()
    refs, dropped = await resolve_all()
    print(f"{len(refs)} resolved, dropped {len(dropped)}: {dropped}")
    room = await room_scores(refs)
    guess = await llm_scores(refs)
    result = summarise(refs, room, guess)
    result["dropped"] = dropped
    result["cities"] = CITIES
    result["seconds"] = round(time.time() - t)
    (HERE / "results.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    t = result["top1"]
    lines = [f"Home city found, {result['n']} references across {len(CITIES)} cities: "
             f"Qloo map alone {t['qloo_map']:.0%} · Gemini alone {t['llm']:.0%} · Room {t['room']:.0%}", "",
             "| Reference | Home | Qloo map alone | Gemini alone | Room |", "|---|---|---|---|---|"]
    for r in result["rows"]:
        mark = lambda x: f"**{x}**" if x == r["home"] else (x or "no map data")
        lines.append(f"| {r['name']} | {r['home']} | {mark(r['qloo_map_top'])} | {mark(r['llm_top'])} | {mark(r['room_top'])} |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
