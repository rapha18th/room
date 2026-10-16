"""Room as an MCP server, so any agent can read the room mid-task.

Mounted on the API at /mcp (streamable HTTP, stateless). Four tools:
  read_room          every reference in a text, scored per city
  score_reference    one reference across a room
  find_swap          local equivalents for a reference that keep its job in the line
  rewrite_for_city   the rewrite agent, run on the server, with its trace
  suggest_for_city   the culture spellchecker for one city, as suggestions
  check_scene        the picture check: every element in an ad frame, scored for a brand in each city
"""

import asyncio
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

import agent
import engine
import llm
import scene
from cache import Cache, cache

server = MCPServer(
    name="Room",
    title="Room: read the room before you walk in",
    instructions=(
        "Room checks cultural references (brands, artists, shows, films, people, places, teams) against a "
        "live audience in specific cities, using Qloo's taste graph. Use read_room on a draft before it goes "
        "to an audience, score_reference for a single name, find_swap when a reference dies in a city, and "
        "rewrite_for_city to let Room's agent tune a whole script for one city (it swaps, drops or keeps each weak reference), and "
        "check_scene on an ad frame to see whether what is on the TV, in hand or on the wall fits a brand in each city. Cities are plain names such as "
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
        raise ToolError("Give at least one city")
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


@server.tool(description="Review a text for an audience in one city, like a spellchecker for culture: for every reference "
                         "that falls flat there, Room suggests a local swap (tested with Qloo) or a cut, or explains why "
                         "it keeps it. Nothing is applied; you choose which suggestions to use.")
async def suggest_for_city(text: str, city: str, age: str | None = None) -> dict:
    cities = _cities([city])
    refs = await _read(text[:20000], cities, age)
    p = await agent.plan(text, refs, city)
    exclude = [r["match"]["entity_id"] for r in refs if r.get("match")]
    taken: set[str] = set()
    out = []
    for step in p["plan"]:
        ref = next((r for r in refs if r["id"] == step["ref_id"]), None)
        if not ref:
            continue
        item = {"reference": ref["surface"], "line": ref["sentence"], "action": step["action"], "why": step["why"]}
        proposal = None
        if step["action"] == "swap":
            f = await agent.find(ref, city, exclude + sorted(taken))
            picks = [x for x in f["picks"] if x["candidate"]["entity_id"] not in taken]
            if picks:
                t = await agent.test(text, refs, ref["id"], picks, city, cities, age, apply_it=False)
                proposal = t["proposal"]
            if not proposal and agent.verdict_of(ref, city) == "dies":
                proposal = (await agent.cut(text, refs, ref["id"], city, apply_it=False))["proposal"]
        elif step["action"] == "drop":
            proposal = (await agent.cut(text, refs, ref["id"], city, apply_it=False))["proposal"]
        if proposal:
            if proposal.get("candidate"):
                taken.add(proposal["candidate"]["entity_id"])
            item.update(action=proposal["action"], suggestion=proposal["line"], replacement=proposal.get("after"),
                        verdict_now=proposal.get("verdict_before"), verdict_after=proposal.get("verdict_after"),
                        why=proposal.get("why") or item["why"])
        elif step["action"] != "keep":
            item.update(action="keep", why=f"Nothing local beats {ref['surface']} in {city}.")
        out.append(item)
    return {"city": city, "room_score": p["before"], "suggestions": out}


MAX_IMAGE = 8 * 1024 * 1024
SCENE_HOUR = 20   # per instance
SCENE_DAY = 300   # across every instance (Firestore budget)
_scene_calls: list[float] = []
_scene_jobs = asyncio.Semaphore(2)


async def _fetch_image(url: str) -> bytes:
    """An https image on port 443 at a public address: no redirects, 8 MB at most, 25 seconds in all."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    import httpx
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or (u.port not in (None, 443)):
        raise ToolError("image_url must be an https URL on the standard port")
    infos = await asyncio.to_thread(socket.getaddrinfo, u.hostname, 443)
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ToolError("image_url must point to a public address")

    async def get():
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            async with c.stream("GET", url, headers={"Accept-Encoding": "identity"}) as r:
                if r.status_code != 200:
                    raise ToolError(f"image_url answered {r.status_code}")
                if int(r.headers.get("content-length") or 0) > MAX_IMAGE:
                    raise ToolError("image_url is over 8 MB")
                data = bytearray()
                async for chunk in r.aiter_raw():
                    data += chunk
                    if len(data) > MAX_IMAGE:
                        raise ToolError("image_url is over 8 MB")
                return bytes(data)
    try:
        return await asyncio.wait_for(get(), 25)
    except asyncio.TimeoutError:
        raise ToolError("image_url took too long to answer")
    except httpx.HTTPError:
        raise ToolError("image_url could not be fetched")


@server.tool(description="Check an ad frame for cultural fit, like a spellchecker for pictures. Room reads every cultural "
                         "element (what is on the TV, in hand, on a shirt or a wall), then scores each one for the brand "
                         "and for audiences in up to four cities with Qloo: how the brand's fans lean toward it against "
                         "Coca-Cola's fans (Room's mass-brand control), who holds it in Qloo's brand records (the brand "
                         "itself or a competitor), and how each city feels about it. Flagged elements come with the best "
                         "local alternative. Pass the picture as image_base64 (JPEG, PNG or WebP, 8 MB at most) or as an "
                         "https image_url.")
async def check_scene(brand: str, cities: list[str], image_base64: str = "", image_url: str = "",
                      age: str | None = None) -> dict:
    import base64
    import binascii
    cities = _cities(cities)
    brand = (brand or "").strip()[:80]
    if not brand:
        raise ToolError("Give a brand")
    age = ",".join(a.strip() for a in age.split(",") if a.strip()) if age else None
    if age and any(a not in engine.AGES for a in age.split(",")):
        raise ToolError("age must be one or more of " + ", ".join(engine.AGES))
    now = time.time()
    _scene_calls[:] = [t for t in _scene_calls if now - t < 3600]
    if len(_scene_calls) >= SCENE_HOUR:
        raise ToolError("Room is checking pictures for a crowd. Try again in a few minutes.")
    if image_base64:
        raw = image_base64.split(",")[-1]
        if len(raw) > MAX_IMAGE * 4 // 3 + 4:
            raise ToolError("image_base64 is over 8 MB")
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ToolError("image_base64 is not valid base64")
    elif image_url:
        data = await _fetch_image(image_url)
    else:
        raise ToolError("Give image_base64 or image_url")
    mime = scene.sniff(data)
    if not mime:
        raise ToolError("The picture must be JPEG, PNG or WebP")
    try:
        data, mime = await asyncio.to_thread(scene.shrink, data, mime)
    except ValueError as e:
        raise ToolError(str(e))
    except Exception:
        raise ToolError("Room could not open that picture")
    key = Cache.key("scene_read", scene.frame_key([(data, mime, None)]), llm.MODEL)
    hit = await cache.get(key)
    if hit:
        read = hit["scene"]
    else:
        if not await cache.spend("mcp_scene", SCENE_DAY):
            raise ToolError("Room has checked its share of pictures for today")
        _scene_calls.append(now)
        async with _scene_jobs:
            read = await scene.read([(data, mime, None)])
        await cache.set(key, {"scene": read}, keep=False)
    fit = await scene.fit(brand, read["elements"], cities, age)
    if fit.get("error"):
        raise ToolError(fit["error"])
    return {
        "brand": fit["brand"]["name"], "brand_partnerships": fit["brand"]["partnership"],
        "lift_control": fit["brand"]["control"],
        "scene_score": fit["scene_score"], "setting": read.get("setting"),
        "elements": [{
            "what": e.get("what"), "where": e.get("slot"), "read_as": (e.get("read_as") or {}).get("name"),
            "lift_vs_control_fans": e.get("lift"), "held_by": e.get("ownership"),
            "cities": {c: {"verdict": v["label"], "why": v["why"],
                           "show_instead": (v.get("pick") or {}).get("name")} for c, v in (e.get("cities") or {}).items()},
        } for e in fit["elements"] if e.get("route") != "off_graph"],
        "also_in_frame": [e.get("what") for e in fit["elements"] if e.get("route") == "off_graph"],
    }


def app():
    """Starlette app for mounting under /mcp. Stateless, JSON responses, any Host header (Cloud Run)."""
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
