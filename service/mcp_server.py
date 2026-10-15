"""Room as an MCP server, so any agent can read the room mid-task.

Mounted on the API at /mcp (streamable HTTP, stateless). Four tools:
  read_room          every reference in a text, scored per city
  score_reference    one reference across a room
  find_swap          local equivalents for a reference that keep its job in the line
  rewrite_for_city   the rewrite agent, run on the server, with its trace
"""

import asyncio

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

import agent
import engine
import llm

server = MCPServer(
    name="Room",
    title="Room: read the room before you walk in",
    instructions=(
        "Room checks cultural references (brands, artists, shows, films, people, places, teams) against a "
        "live audience in specific cities, using Qloo's taste graph. Use read_room on a draft before it goes "
        "to an audience, score_reference for a single name, find_swap when a reference dies in a city, and "
        "rewrite_for_city to let Room's agent tune a whole script for one city (it swaps, drops or keeps each weak reference). Cities are plain names such as "
        "'Atlanta' or 'Lagos'; up to four per call. Age bands: 24_and_younger, 25_to_29, 30_to_34, 35_to_44, "
        "45_to_54, 55_and_older (comma-separate to combine)."
    ),
    website_url="https://sozoroom.web.app",
)

MAX_CITIES = 4
MAX_REFS = 12


def _cities(cities: list[str]) -> list[str]:
    out = [c.strip() for c in cities if c and c.strip()][:MAX_CITIES]
    if not out:
        raise ValueError("Give at least one city")
    return out


def _brief(score: dict) -> dict:
    return {c: {"verdict": v["verdict"], "known": v["known"], "loved": v["loved"], "why": v["why"]}
            for c, v in (score.get("cities") or {}).items()}


async def _read(text: str, cities: list[str], age: str | None) -> list[dict]:
    refs = (await llm.extract(text))[:MAX_REFS]

    async def one(i, r):
        r["id"] = f"r{i}"
        if r["type"] not in engine.TYPES:
            r.update(match=None, outside=True)
            return r
        r.update(await engine.resolve(r["name"], r["type"]), outside=False)
        if r.get("match"):
            r["score"] = await engine.score(r["match"], r["type"], cities, age)
        return r

    sem = asyncio.Semaphore(3)

    async def guarded(i, r):
        async with sem:
            return await one(i, r)

    return await asyncio.gather(*[guarded(i, r) for i, r in enumerate(refs)])


@server.tool(description="Find every cultural reference in a text and score each one for an audience in each city. "
                         "Returns verdicts (lands, roast, famous, inside, dies), Known and Loved per city, and a room "
                         "score per city.")
async def read_room(text: str, cities: list[str], age: str | None = None) -> dict:
    cities = _cities(cities)
    refs = await _read(text[:6000], cities, age)
    return {
        "room_score": {c: agent.room_score(refs, c) for c in cities},
        "references": [{
            "reference": r["surface"],
            "job_in_line": r.get("role"),
            "matched_to": (r.get("match") or {}).get("name"),
            "outside_graph": r.get("outside", False),
            "cities": _brief(r["score"]) if r.get("score") else None,
        } for r in refs],
    }


@server.tool(description="Score one reference (a brand, artist, show, film, person, place or team) for audiences in "
                         "up to four cities. kind is one of artist, book, brand, destination, movie, person, place, "
                         "podcast, tv_show, videogame. Sports teams are brand.")
async def score_reference(name: str, kind: str, cities: list[str], age: str | None = None) -> dict:
    cities = _cities(cities)
    m = await engine.resolve(name, kind)
    if not m["match"]:
        return {"matched_to": None, "note": "Qloo holds no clear match",
                "closest": [c["name"] for c in m["candidates"]]}
    s = await engine.score(m["match"], kind, cities, age)
    return {"matched_to": m["match"]["name"], "certain": m["certain"], "cities": _brief(s)}


@server.tool(description="When a reference dies in a city, find local equivalents the audience has affinity for that "
                         "keep the reference's job in the line. Returns rewritten lines, each scored for the city.")
async def find_swap(line: str, reference: str, kind: str, city: str, job_in_line: str = "") -> dict:
    m = await engine.resolve(reference, kind)
    if not m["match"]:
        return {"swaps": [], "note": "Qloo holds no clear match for the reference"}
    cands = await engine.swap_candidates(m["match"], kind, city)
    if not cands:
        return {"swaps": []}
    picks = await llm.pick_swaps(line, reference, job_in_line or "the reference's role in the line", city, cands)
    scores = await asyncio.gather(*[engine.score(p["candidate"], kind, [city]) for p in picks])
    return {"swaps": [{"swap": p["candidate"]["name"], "line": p["line"], "why": p["why"],
                       **_brief(s).get(city, {})} for p, s in zip(picks, scores)]}


@server.tool(description="Run Room's rewrite agent: it plans which weak references to swap or keep for an audience in "
                         "one city, finds local equivalents with Qloo, tests each, and rewrites the script. Returns "
                         "the new script, room scores before and after, and the agent's trace.")
async def rewrite_for_city(text: str, city: str, also_check: list[str] | None = None, max_swaps: int = 3) -> dict:
    cities = _cities([city] + [c for c in (also_check or []) if c != city])
    refs = await _read(text[:6000], cities, None)
    before = {c: agent.room_score(refs, c) for c in cities}
    p = await agent.plan(text, refs, city)
    trace = list(p["trace"])
    swaps = 0
    for step in p["plan"]:
        if step["action"] == "keep" or swaps >= max(1, min(max_swaps, 6)):
            continue
        ref = next((r for r in refs if r["id"] == step["ref_id"]), None)
        if not ref:
            continue
        t = None
        if step["action"] == "swap":
            f = await agent.find(ref, city, [r["match"]["entity_id"] for r in refs if r.get("match")])
            trace += f["trace"]
            if f["picks"]:
                t = await agent.test(text, refs, ref["id"], f["picks"], city, cities, None)
                trace += t["trace"]
        swap_failed = step["action"] == "swap" and not (t and t["applied"])
        if step["action"] == "drop" or (swap_failed and agent.verdict_of(ref, city) == "dies"):
            t = await agent.cut(text, refs, ref["id"], city)
            trace += t["trace"]
        if t and t["applied"]:
            text, refs, swaps = t["text"], t["refs"], swaps + 1
        if (agent.room_score(refs, city) or 0) >= agent.TARGET:
            break
    return {
        "script": text,
        "room_score_before": before,
        "room_score_after": {c: agent.room_score(refs, c) for c in cities},
        "trace": [f"[{e['who']}] {e['text']}" for e in trace],
    }


def app():
    """Starlette app for mounting under /mcp. Stateless, JSON responses, any Host header (Cloud Run)."""
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
