"""Room as an MCP server, so any agent can read the room mid-task.

Mounted on the API at /mcp (streamable HTTP, stateless). Tools:
  pitch              a launch brief in, up to three ideas built only from what its audience loves out, each name with its lift
  read_audience      what fans of one thing love more than a household name's fans do, across nine kinds of culture
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
import pitch as pitching
import scene
from cache import Cache, cache

server = MCPServer(
    name="Room",
    title="Room: read the room before you walk in",
    instructions=(
        "Use pitch when you hold a launch brief (a product, an album, a film, a game, a book, an opening) and need "
        "ideas grounded in what its audience loves: it returns up to three ideas whose names are Qloo records with their "
        "lift. Use read_audience to see what fans of one thing love more than fans of a household name of the same "
        "kind do. "
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


PITCH_HOUR = 20     # per instance
READ_HOUR = 60      # per instance, for read_audience
PITCH_DAY = 200     # across every instance (Firestore budget)
_calls: dict[str, list[float]] = {}


def _age(age: str | None) -> str | None:
    bands = [a.strip() for a in (age or "")[:80].split(",") if a.strip()]
    if any(a not in engine.AGES for a in bands):
        raise ToolError("age must be one or more of " + ", ".join(engine.AGES))
    return ",".join(bands) or None


def _slow_down(bucket: str, per_hour: int):
    now = time.time()
    xs = [t for t in _calls.get(bucket, []) if now - t < 3600]
    if len(xs) >= per_hour:
        raise ToolError("Room is pitching for a crowd. Try again in a few minutes.")
    _calls[bucket] = xs + [now]


@server.tool(description="Read an audience the way Qloo sees it: what fans of one brand, artist, film, show, book, game, "
                         "podcast, person or destination love more than fans of a household name of the same kind do "
                         "(the lift), across music, shows, films, podcasts, brands, people, games, books and travel, with "
                         "the taste words that run through those loves. kind is optional (artist, brand, movie, tv_show, "
                         "book, videogame, podcast, person, destination).")
async def read_audience(subject: str, kind: str = "", age: str | None = None) -> dict:
    subject = (subject or "").strip()[:120]
    if not subject:
        raise ToolError("Give a subject")
    age = _age(age)
    _slow_down("read", READ_HOUR)
    etype = kind if kind in engine.TYPES and kind != "place" else None
    if etype:
        m, etype = await pitching.resolve_any(subject, etype)
        hit = m.get("match")
    else:
        hits = [h for h in await engine.search(subject, None) if h.get("type") in engine.TYPES and h.get("type") != "place"
                and engine.match_quality(subject, h["name"]) >= engine.MIN_MATCH]
        hit = hits[0] if hits else None
        etype = hit.get("type") if hit else None
    if not hit:
        raise ToolError(f"{subject} is new to Qloo")
    ls = await pitching.lanes([hit["entity_id"]], etype, age, [hit["name"]])
    th = await pitching.threads(ls, age)
    ctrl = ls[0]["control"]
    return {
        "subject": hit["name"], "type": etype, "measured_against": f"{ctrl['name']}'s fans",
        "loves": {l["label"]: [{"name": r["name"], "lift": r["lift"]} for r in l["rows"] if r.get("lift") is not None][:6]
                  for l in ls if not l["fold"]},
        "folded": [l["label"] for l in ls if l["fold"]],
        "threads": [t["word"] for t in th],
        "note": "Lift is the subject's fans' affinity minus the affinity of fans of a household name of the same kind, "
                "on the same list, from Qloo.",
    }


@server.tool(description="Pitch a launch. Give a one-line brief (what is launching, for whom, where), for example 'A debut "
                         "album for fans of SZA and Daniel Caesar. London, Atlanta, Lagos.' Room reads who loves it with "
                         "Qloo, maps where those fans are and the rooms they gather in, and returns up to three ideas built "
                         "only from those names, read back by Room's script reader. Every artist, brand, show, film, book, "
                         "game, podcast and room in an idea is a Qloo record: cultural names carry their lift, rooms their "
                         "city. The words are Gemini's. Cities override the brief's; up to four.")
async def pitch(brief: str, cities: list[str] | None = None, age: str | None = None) -> dict:
    brief = (brief or "").strip()[:2000]
    if len(brief) < 3:
        raise ToolError("Give a one-line brief")
    age = _age(age)
    t0 = time.time()
    b = await pitching.brief_cached(brief)
    p = pitching.params_from(b)
    if not p["subjects"]:
        raise ToolError(f"{b['subjects'][0]['name'] if b['subjects'] else 'Every name in this brief'} is new to Qloo. "
                        "Name what its people already love: 'for fans of ...'")
    if cities:
        p["cities"] = [c[:60] for c in _cities(cities)]
    p["cities"] = p["cities"] or ["New York", "London"]
    p["age"] = pitching.norm_age(age or p["age"], p["alcohol"])
    key = pitching.mcp_key(p)
    # A finished or running pitch costs nothing: the hourly slot and the daily budget pay for new work only.
    if not (await cache.get(key) or key in pitching._inflight):
        _slow_down("pitch", PITCH_HOUR)
        if not await cache.spend("mcp_pitch", PITCH_DAY):
            raise ToolError("Room has pitched its share for today")
    try:
        out = await asyncio.wait_for(asyncio.shield(pitching.write_cached(p, keep=bool(b.get("sample")))),
                                     max(15.0, 54 - (time.time() - t0)))
    except asyncio.TimeoutError:
        raise ToolError("Room is still writing this pitch. Call pitch again with the same brief in about thirty seconds; "
                        "the same server usually has it ready.")
    pk = await pitching.pack(p)
    return {
        "launch": out["launch"], "measured_against": f"{pk['control']['name']}'s fans",
        "cities": {c: {"role": pk["where"]["cities"][c]["role"], "why": pk["where"]["cities"][c]["line"]} for c in pk["where"]["order"]},
        "cities_source": "Known is Gemini's estimate with a Qloo floor; Loved is Qloo's heatmap.",
        "threads": [t["word"] for t in pk["threads"]],
        "ideas": [{"title": pitching.filler(i, pk)(i["title"]), "text": i["text"], "lead_city": i["lead_city"],
                   "names": {pitching.SLOT_LABEL[k]: {"name": v["name"], "lift": v.get("lift"), "city": v.get("city")}
                             for k, v in i["slots"].items()}} for i in out["ideas"]],
        "read_back": out.get("tally"),
        "note": out.get("note") or "Room's proposals, built from audience signals. Names and lifts from Qloo; words from Gemini.",
        **({"age_note": pitching.ALCOHOL_NOTE} if p["alcohol"] else {}),
    }


def app():
    """Starlette app for mounting under /mcp. Stateless, JSON responses, any Host header (Cloud Run)."""
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
