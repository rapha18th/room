import asyncio, json, sys, time
sys.path.insert(0, ".")
import os
os.environ.setdefault("ROOM_DISK_CACHE", "../spike/out/cache")
from dotenv import load_dotenv; load_dotenv("../.env")
import engine, llm

TEXT = """I flew into Dallas at 2am and the only thing open was a Whataburger. My cousin from London said that's just Greggs in a cowboy hat. He spent the whole flight watching Coronation Street on his phone, volume up, like the plane needed to know who cheated on who. I tried to fix the mood with some Kabza De Small. The guy in 14C asked if that was a new kind of yoga. So I put on Nickelback. Everyone hated it. Everyone knew every word. We landed, he bought Crocs at the airport, and I knew right then: this man has given up, and he has never been happier."""
CITIES = ["Dallas", "London", "Johannesburg", "Lagos"]

async def main():
    t = time.time()
    refs = await llm.extract(TEXT)
    print(f"extract {time.time()-t:.1f}s:", [(r["surface"], r["type"], r["role"]) for r in refs])
    t = time.time()
    matched = await asyncio.gather(*[engine.resolve(r["name"], r["type"]) for r in refs if r["type"] in engine.TYPES])
    print(f"resolve {time.time()-t:.1f}s")
    pairs = [(r, m) for r, m in zip([r for r in refs if r["type"] in engine.TYPES], matched) if m["match"]]
    for r, m in pairs:
        print(f"  {r['surface']:20s} -> {m['match']['name']} ({m['match']['type']}) certain={m['certain']}")
    sem = asyncio.Semaphore(3)
    async def sc(r, m):
        async with sem:
            t0 = time.time()
            s = await engine.score(m["match"], r["type"], CITIES)
            return r, s, time.time() - t0
    t = time.time()
    for r, s, dt in await asyncio.gather(*[sc(r, m) for r, m in pairs]):
        row = "  ".join(f"{c[:6]}:{v['verdict']:6s} k{v['known']:.2f} l{v['loved'] if v['loved'] is not None else '-'}" for c, v in s["cities"].items())
        print(f"  {r['surface'][:18]:18s} [{s['mode']}] {dt:4.1f}s  {row}")
    print(f"score all {time.time()-t:.1f}s")
    # swap Whataburger for London
    r, m = next((r, m) for r, m in pairs if "Whataburger" in r["surface"])
    t = time.time()
    cands = await engine.swap_candidates(m["match"], r["type"], "London")
    picks = await llm.pick_swaps(r["sentence"], r["surface"], r["role"], "London", cands)
    print(f"swap {time.time()-t:.1f}s, {len(cands)} candidates")
    for p in picks:
        s = await engine.score(p["candidate"], r["type"], CITIES)
        print("  ->", p["candidate"]["name"], "|", s["cities"]["London"]["verdict"], s["cities"]["London"]["known"], "|", p["line"])

asyncio.run(main())
