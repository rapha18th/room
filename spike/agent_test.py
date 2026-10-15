import asyncio, os, sys, time, re, json
sys.path.insert(0, ".")
os.environ.setdefault("ROOM_DISK_CACHE", "../.cache")
from dotenv import load_dotenv; load_dotenv("../.env")
import engine, llm, agent

src = open("../web/app.js", encoding="utf-8").read()
cities_s, TEXT = re.findall(r'cities: (\[[^\]]*\]), text:\n`(.*?)`', src, flags=re.S)[int(sys.argv[1]) if len(sys.argv) > 1 else 0]
CITIES = json.loads(cities_s); CITY = sys.argv[2] if len(sys.argv) > 2 else CITIES[0]; TEXT = TEXT.strip()

async def main():
    refs = await llm.extract(TEXT)
    out = []
    for i, r in enumerate(refs):
        if r["type"] in engine.TYPES:
            m = await engine.resolve(r["name"], r["type"]); r.update(m); r["outside"] = False
        else:
            r.update(match=None, candidates=[], certain=False, outside=True)
        r["id"] = f"r{i}"
        if r.get("match"):
            r["score"] = await engine.score(r["match"], r["type"], CITIES)
        out.append(r)
    text, refs = TEXT, out
    t = time.time(); p = await agent.plan(text, refs, CITY)
    for e in p["trace"]: print(f"[{e['who']:6s}] {e['text']}  {e.get('ms','')}")
    for step in p["plan"]:
        if step["action"] != "swap": continue
        ref = next(r for r in refs if r["id"] == step["ref_id"])
        f = await agent.find(ref, CITY, [r["match"]["entity_id"] for r in refs if r.get("match")])
        for e in f["trace"]: print(f"[{e['who']:6s}] {e['text']}  {e.get('ms','')}")
        if not f["picks"]: continue
        res = await agent.test(text, refs, ref["id"], f["picks"], CITY, CITIES, None)
        for e in res["trace"]: print(f"[{e['who']:6s}] {e['text']}  {e.get('ms','')}")
        text, refs = res["text"], res["refs"]
        if (agent.room_score(refs, CITY) or 0) >= 80: print("target reached"); break
    print(f"\n{time.time()-t:.0f}s total\n{text}\n")
    print({c: agent.room_score(refs, c) for c in CITIES})

asyncio.run(main())
