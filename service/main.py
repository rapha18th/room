"""Room API. Hosting rewrites /api/** here; locally it also serves ../web."""

import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from typing import Annotated, Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

import agent  # noqa: E402
import docs  # noqa: E402
import engine  # noqa: E402
from cache import cache, Cache  # noqa: E402
import llm  # noqa: E402
import pitch  # noqa: E402
import scene  # noqa: E402
from qloo import QlooError  # noqa: E402

import contextlib  # noqa: E402

import mcp_server  # noqa: E402

_mcp_app = mcp_server.app()


@contextlib.asynccontextmanager
async def lifespan(_):
    async with mcp_server.server.session_manager.run():
        yield


app = FastAPI(title="Room", lifespan=lifespan)
app.mount("/mcp", _mcp_app)


class _McpSlash:
    """MCP clients post to /mcp; the mounted app answers at /mcp/. Rewrite before routing, no redirect."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.inner(scope, receive, send)


app.add_middleware(_McpSlash)

MAX_TEXT = 40000  # long enough for a deck or a short document
MAX_REFS = 60
MAX_CITIES = 8  # a room shows up to 4 cities; a tour runs up to 8 stops
READ_VERSION = 5  # bump when the extraction prompt changes

# ---------- light per-IP limiter: the demo spends a shared key ----------
_hits: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    """The caller as the last trusted hop saw it. Behind Firebase Hosting the header reads 'client, hosting-proxy'
    (logged on Cloud Run), so the client sits second from the right; a direct call's client is the rightmost entry.
    The leftmost entry is whatever the caller wrote, so it never counts. Per-instance caps back this up."""
    hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
    if not hops:
        return (request.client.host if request.client else "?")[:64]
    hosted = "firebase hosting" in (request.headers.get("via") or "").lower()
    return (hops[-2] if hosted and len(hops) >= 2 else hops[-1])[:64]


def limit(request: Request, per_min: int):
    """Per IP and per endpoint, so a read and its dozen score calls count separately."""
    key = f"{client_ip(request)}|{request.url.path}"
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < 60]
    if len(recent) >= per_min:
        raise HTTPException(429, "Easy. Give the room a minute.")
    recent.append(now)
    _hits[key] = recent
    if len(_hits) > 20000:
        for k in [k for k, v in _hits.items() if now - v[-1] > 60]:
            del _hits[k]


@app.exception_handler(QlooError)
async def qloo_error(_, e: QlooError):
    return JSONResponse({"detail": str(e)}, status_code=502 if e.status >= 500 else 400)


@app.exception_handler(ValueError)
async def value_error(_, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.get("/api/health")
async def health():
    return {"ok": True, "model": llm.MODEL, "anchors": engine.ANCHORS}


class ReadIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    keep: bool = False   # True for the built-in samples: the shared cache keeps them warm for everyone


@app.post("/api/read")
async def read(body: ReadIn, request: Request):
    """Pull references out of the text and match each to a Qloo entity."""
    limit(request, 12)
    hit = await cache.get(Cache.key("read", body.text, llm.MODEL, READ_VERSION))
    if hit:
        return hit
    refs = await llm.extract(body.text)

    async def match(r):
        if r["type"] not in engine.TYPES:
            return {**r, "match": None, "candidates": [], "certain": False, "outside": True}
        m = await engine.resolve(r["name"], r["type"])
        return {**r, **m, "outside": False}

    out = await asyncio.gather(*[match(r) for r in refs[:MAX_REFS]])
    for i, r in enumerate(out):
        r["id"] = f"r{i}"
    result = {"references": out}
    if out:
        await cache.set(Cache.key("read", body.text, llm.MODEL, READ_VERSION), result, keep=body.keep)
    return result


class ScoreIn(BaseModel):
    entity: dict
    type: str
    cities: list[str] = Field(min_length=1, max_length=MAX_CITIES)
    age: str | None = None


@app.post("/api/score")
async def score(body: ScoreIn, request: Request):
    limit(request, 120)
    if body.type not in engine.TYPES:
        raise HTTPException(400, "That type sits outside Qloo's graph")
    check_age(body.age)
    return await engine.score(body.entity, body.type, body.cities, body.age)


def check_age(age: str | None):
    if age and any(a not in engine.AGES for a in age.split(",")):
        raise HTTPException(400, f"Age bands must come from {engine.AGES}")


class SwapIn(BaseModel):
    entity: dict
    type: str
    surface: str
    role: str
    sentence: str
    city: str
    cities: list[str] = Field(min_length=1, max_length=MAX_CITIES)
    age: str | None = None
    exclude: list[str] = Field(default_factory=list, max_length=40)


@app.post("/api/swap")
async def swap(body: SwapIn, request: Request):
    """Local equivalents that keep the reference's job. The client scores each pick with /api/score."""
    limit(request, 20)
    check_age(body.age)
    cands = await engine.swap_candidates(body.entity, body.type, body.city, set(body.exclude))
    if not cands:
        return {"swaps": []}
    return {"swaps": await llm.pick_swaps(body.sentence, body.surface, body.role, body.city, cands)}


# ---------- second opinion: Gemini alone, with no Qloo data ----------

class GuessIn(BaseModel):
    refs: list[dict] = Field(max_length=MAX_REFS)
    cities: list[str] = Field(min_length=1, max_length=MAX_CITIES)
    age: str | None = None


@app.post("/api/guess")
async def guess(body: GuessIn, request: Request):
    limit(request, 20)
    check_age(body.age)
    refs = [{"id": r["id"], "name": r["name"], "type": r.get("type", "brand")} for r in body.refs]
    key = Cache.key("guess", refs, body.cities, body.age, llm.MODEL)
    hit = await cache.get(key)
    if hit:
        return hit
    out = {"guess": await llm.guess_room(refs, body.cities, body.age)}
    await cache.set(key, out)
    return out


# ---------- the rewrite agent: one short step per request ----------

class AgentPlanIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    refs: list[dict] = Field(max_length=MAX_REFS)
    city: str


@app.post("/api/agent/plan")
async def agent_plan(body: AgentPlanIn, request: Request):
    limit(request, 12)
    return await agent.plan(body.text, body.refs, body.city)


class AgentFindIn(BaseModel):
    ref: dict
    city: str
    exclude: list[str] = Field(default_factory=list, max_length=40)


@app.post("/api/agent/find")
async def agent_find(body: AgentFindIn, request: Request):
    limit(request, 120)
    return await agent.find(body.ref, body.city, body.exclude)


class AgentTestIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    refs: list[dict] = Field(max_length=MAX_REFS)
    ref_id: str
    picks: list[dict] = Field(max_length=3)
    city: str
    cities: list[str] = Field(min_length=1, max_length=MAX_CITIES)
    age: str | None = None
    apply: bool = True


@app.post("/api/agent/test")
async def agent_test(body: AgentTestIn, request: Request):
    limit(request, 120)
    check_age(body.age)
    return await agent.test(body.text, body.refs, body.ref_id, body.picks, body.city, body.cities, body.age,
                            body.apply)


class AgentCutIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    refs: list[dict] = Field(max_length=MAX_REFS)
    ref_id: str
    city: str
    apply: bool = True


@app.post("/api/agent/cut")
async def agent_cut(body: AgentCutIn, request: Request):
    limit(request, 60)
    return await agent.cut(body.text, body.refs, body.ref_id, body.city, body.apply)


# ---------- documents: PDF, PPTX, DOCX, TXT, MD in; the corrected file out ----------

# Large decks unpack into a lot of memory; two document jobs at a time per instance.
_doc_jobs = asyncio.Semaphore(2)


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(docs.MAX_BYTES + 1)
    if len(data) > docs.MAX_BYTES:
        raise HTTPException(413, "Room reads files up to 12 MB.")
    return data


@app.post("/api/doc/parse")
async def doc_parse(request: Request, file: UploadFile = File(...)):
    """Text blocks with stable ids. The browser joins them with blank lines and reads them like a script."""
    limit(request, 20)
    data = await _read_upload(file)
    async with _doc_jobs:
        return await asyncio.to_thread(docs.parse, file.filename or "upload.txt", data)


@app.post("/api/doc/export")
async def doc_export(request: Request, file: UploadFile = File(...), changes: str = Form("[]"),
                     audience: str = Form("")):
    """The original file with the changed blocks rewritten: tracked changes in Word, a change log in a
    deck's speaker notes. A PDF comes back as a tracked Word document."""
    import json
    from urllib.parse import quote

    limit(request, 20)
    try:
        edits = [c for c in json.loads(changes) if isinstance(c, dict)]
    except ValueError:
        raise HTTPException(400, "changes must be a JSON list of {id, text}")
    data = await _read_upload(file)
    async with _doc_jobs:
        name, out, media = await asyncio.to_thread(docs.export, file.filename or "upload.txt", data, edits[:400],
                                                   audience[:60])
    return Response(out, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------- the picture check: frames in, verdicts per element per city, a fix redrawn in place ----------

MAX_IMAGE = 8 * 1024 * 1024
MAX_FRAMES = 16
FIX_PER_HOUR = 12      # per visitor
FIX_INSTANCE_HOUR = 40  # per instance, whatever the headers say
FIX_DAY = 150          # across every instance (Firestore budget)
_fix_hits: dict[str, list[float]] = {}
_fix_all: list[float] = []
_scene_jobs = asyncio.Semaphore(3)
_fix_jobs = asyncio.Semaphore(1)
_shrink_jobs = asyncio.Semaphore(4)


async def _image(file: UploadFile) -> tuple[bytes, str]:
    data = await file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "Room reads pictures up to 8 MB.")
    mime = scene.sniff(data)
    if not mime:
        raise HTTPException(415, "Room reads JPEG, PNG and WebP pictures.")
    async with _shrink_jobs:
        try:
            return await asyncio.to_thread(scene.shrink, data, mime)
        except ValueError as e:
            raise HTTPException(413, str(e))
        except Exception:
            raise HTTPException(415, "Room could not open that picture.")


def _read_key(items) -> str:
    return Cache.key("scene_read", scene.frame_key(items), llm.MODEL)


@app.post("/api/scene/read")
async def scene_read(request: Request, file: UploadFile | None = File(None), frames: list[UploadFile] = File(default=[]),
                     times: str = Form("[]"), keep: bool = Form(False)):
    """One picture, or up to 16 frames sampled from a clip in the browser (each labelled with its time)."""
    import json
    limit(request, 8)
    if len(frames) > MAX_FRAMES:
        raise HTTPException(413, f"Room reads up to {MAX_FRAMES} frames from a clip.")
    items = []
    if file is not None:
        data, mime = await _image(file)
        items.append((data, mime, None))
    try:
        labels = [str(t)[:12] for t in json.loads(times)][:MAX_FRAMES]
    except (ValueError, TypeError):
        labels = []
    for k, f in enumerate(frames):
        data, mime = await _image(f)
        items.append((data, mime, labels[k] if k < len(labels) else None))
    if not items:
        raise HTTPException(400, "Send a picture or frames from a clip.")
    key = _read_key(items)
    hit = await cache.get(key)
    if hit:
        return hit
    async with _scene_jobs:
        out = {"scene": await scene.read(items)}
    # Only the built-in samples go to the shared cache; uploads stay in this instance's memory.
    await cache.set(key, out, keep=keep)
    return out


class SceneEl(BaseModel):
    id: str = Field("", max_length=8)
    slot: str = Field("", max_length=40)
    what: str = Field("", max_length=200)
    kind: str = Field("", max_length=40)
    sport: str = Field("", max_length=40)
    name: str = Field("", max_length=120)
    evokes: str = Field("", max_length=120)
    cue: str = Field("", max_length=200)
    box_2d: list[int] = Field(min_length=4, max_length=4)
    prominence: float | None = None
    t: str = Field("", max_length=24)


class SceneProduct(BaseModel):
    box_2d: list[int] = Field(default_factory=list, max_length=4)


class SceneRead(BaseModel):
    elements: list[SceneEl] = Field(max_length=scene.MAX_ELEMENTS)
    product: SceneProduct = SceneProduct()


class SceneFitIn(BaseModel):
    brand: str = Field(min_length=1, max_length=80)
    elements: list[SceneEl] = Field(max_length=scene.MAX_ELEMENTS)
    cities: list[str] = Field(min_length=1, max_length=4)
    age: str | None = None


@app.post("/api/scene/fit")
async def scene_fit(body: SceneFitIn, request: Request):
    limit(request, 12)
    check_age(body.age)
    out = await scene.fit(body.brand.strip(), [e.model_dump() for e in body.elements],
                          [c.strip()[:60] for c in body.cities], body.age)
    if out.get("error"):
        raise HTTPException(404, out["error"])
    return out


@app.post("/api/scene/fix")
async def scene_fix(request: Request, file: UploadFile = File(...), element_id: str = Form("", max_length=8),
                    box: str = Form(..., max_length=80), pick: str = Form(..., max_length=80)):
    """Redraw only the flagged element's box with a catalog property's sport. Every word of the prompt comes from the
    server: the element as Room read this picture, and the catalog's description of the sport."""
    import json
    limit(request, 3)
    try:
        b = [int(v) for v in json.loads(box)]
        if len(b) != 4:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(400, "box must be four numbers.")
    p = await scene.prop(pick)
    if not p:
        raise HTTPException(400, "Room draws only the properties it scores.")
    now = time.time()
    ip = client_ip(request)
    mine = [t for t in _fix_hits.get(ip, []) if now - t < 3600]
    _fix_all[:] = [t for t in _fix_all if now - t < 3600]
    if len(mine) >= FIX_PER_HOUR:
        raise HTTPException(429, "Room redraws twelve pictures an hour per visitor.")
    if len(_fix_all) >= FIX_INSTANCE_HOUR:
        raise HTTPException(429, "Room is drawing for a crowd. Try again in a few minutes.")
    data, mime = await _image(file)
    key = _read_key([(data, mime, None)])
    read = await cache.get(key)
    if not read:
        async with _scene_jobs:
            read = {"scene": await scene.read([(data, mime, None)])}
        await cache.set(key, read, keep=False)
    el = scene.locate(read["scene"], element_id, b)
    if not el:
        raise HTTPException(409, "Room could not find that element in this picture.")
    if not await cache.spend("fix", FIX_DAY):
        raise HTTPException(429, "Room has drawn its share of pictures for today. The check itself still runs.")
    _fix_hits[ip] = mine + [now]
    _fix_all.append(now)
    if len(_fix_hits) > 5000:
        for k in [k for k, v in _fix_hits.items() if not v or now - v[-1] > 3600]:
            del _fix_hits[k]
    async with _fix_jobs:
        try:
            out = await asyncio.wait_for(scene.fix(data, mime, el, p["sport"]), 70)
        except asyncio.TimeoutError:
            raise HTTPException(504, "The redraw took too long. Try again.")
        except RuntimeError as e:
            raise HTTPException(502, str(e))
    return {"image": scene.to_b64(out), "mime": scene.sniff(out) or "image/png", "element": el["id"],
            "drew": p["sport"]}


class SceneCheckIn(BaseModel):
    before: SceneRead
    after: SceneRead
    element_id: str = Field(max_length=8)
    pick: str = Field(max_length=80)


@app.post("/api/scene/check")
async def scene_check(body: SceneCheckIn, request: Request):
    """Read-back: the redrawn slot shows the pick's sport, and the rest of the frame held."""
    limit(request, 20)
    p = await scene.prop(body.pick)
    if not p:
        raise HTTPException(400, "Room checks only the properties it scores.")
    return await asyncio.to_thread(scene.check, body.before.model_dump(), body.after.model_dump(), body.element_id,
                                   p["sport"])


# ---------- Pitch: a brief in, the audience's world and three grounded ideas out ----------

WRITE_DAY = 800   # writer, read-back and rollout calls across every instance per day
READ_DAY = 3000   # brief and what-if reads across every instance per day
PITCH_BODY = 64 * 1024
_pitch_hour: dict[str, list[float]] = {}
# Per instance, whatever the headers say: the per-IP limiter keys on a header a caller can write.
PITCH_INSTANCE_HOUR = {"brief": 240, "whatif": 240, "write": 180, "readback": 180, "rollout": 120, "qloo": 1200}

Short = Annotated[str, Field(max_length=60)]
Note = Annotated[str, Field(max_length=160)]


class PitchBriefIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


class PitchSubject(BaseModel):
    id: str = Field("", max_length=64)
    type: str = Field(max_length=16)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field("subject", max_length=8)


class PitchParams(BaseModel):
    subjects: list[PitchSubject] = Field(min_length=1, max_length=3)
    cities: list[Short] = Field(min_length=1, max_length=4)
    age: str | None = Field(None, max_length=80)
    categories: list[Annotated[str, Field(max_length=32)]] = Field(default_factory=list, max_length=4)
    kind: str = Field("campaign", max_length=16)
    news: str = Field("", max_length=80)
    when: str = Field("", max_length=40)
    avoid: list[Short] = Field(default_factory=list, max_length=5)
    alcohol: bool = False


class PitchLaneIn(PitchParams):
    lane: str = Field(max_length=16)


class PitchCityIn(PitchParams):
    city: str = Field(min_length=1, max_length=60)


class PitchPin(BaseModel):
    id: str = Field(max_length=64)
    lane: str = Field(max_length=16)


class SlotRef(BaseModel):
    id: str = Field(max_length=64)


class PitchIdea(BaseModel):
    id: str = Field("", max_length=24)
    title: str = Field("", max_length=600)
    line: str = Field("", max_length=600)
    insight: str = Field("", max_length=600)
    idea: str = Field("", max_length=600)
    slots: dict[Literal["partner", "venue", "media", "sound", "look"], SlotRef] = Field(default_factory=dict)
    threads: list[Annotated[str, Field(max_length=30)]] = Field(default_factory=list, max_length=2)
    lead_city: str = Field("", max_length=60)


class PitchWriteIn(PitchParams):
    sample: str = Field("", max_length=8)
    seed: int = Field(0, ge=0, le=999)
    kept: list[Note] = Field(default_factory=list, max_length=3)
    killed: list[Note] = Field(default_factory=list, max_length=6)
    answer: str = Field("", max_length=400)
    tone: str = Field("", max_length=160)
    pins: list[PitchPin] = Field(default_factory=list, max_length=4)


class PitchIdeasIn(PitchParams):
    sample: str = Field("", max_length=8)
    seed: int = Field(0, ge=0, le=999)
    ideas: list[PitchIdea] = Field(min_length=1, max_length=3)
    pins: list[PitchPin] = Field(default_factory=list, max_length=4)


class PitchIdeaIn(PitchParams):
    sample: str = Field("", max_length=8)
    idea: PitchIdea
    pins: list[PitchPin] = Field(default_factory=list, max_length=4)


class PitchItemIn(PitchParams):
    id: str = Field(max_length=64)
    pins: list[PitchPin] = Field(default_factory=list, max_length=4)


class PitchWhatIfIn(PitchParams):
    text: str = Field(min_length=1, max_length=200)


class _PitchBodyCap:
    """Pitch bodies are small JSON. Read each one up to the cap as it streams (a chunked request carries no
    Content-Length), then hand it on."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/pitch/"):
            await self.inner(scope, receive, send)
            return
        too_big = JSONResponse({"detail": "That request is too large."}, status_code=413)
        if any(k == b"content-length" and int(v or 0) > PITCH_BODY for k, v in scope.get("headers", [])):
            await too_big(scope, receive, send)
            return
        chunks, size = [], 0
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body = msg.get("body", b"")
            size += len(body)
            if size > PITCH_BODY:
                await too_big(scope, receive, send)
                return
            chunks.append(body)
            if not msg.get("more_body"):
                break
        data, sent = b"".join(chunks), False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": data, "more_body": False}
            return await receive()
        await self.inner(scope, replay, send)


app.add_middleware(_PitchBodyCap)


def _cap(name: str):
    now = time.time()
    xs = [t for t in _pitch_hour.get(name, []) if now - t < 3600]
    if len(xs) >= PITCH_INSTANCE_HOUR[name]:
        raise HTTPException(429, "Room is pitching for a crowd. Try again in a few minutes.")
    _pitch_hour[name] = xs + [now]


def _pitch(body: PitchParams) -> dict:
    """The pitch parameters alone (never the round's notes), normalised the same way for every endpoint."""
    check_age(body.age)
    p = body.model_dump(include=set(PitchParams.model_fields))
    p["cities"] = [c.strip() for c in p["cities"] if c.strip()][:4]
    p["avoid"] = [a.strip() for a in p["avoid"] if a.strip()]
    p["age"] = pitch.norm_age(p["age"], p["alcohol"])
    if not p["cities"]:
        raise HTTPException(400, "Name at least one city.")
    return p


def _pins(body) -> list[dict]:
    return [x.model_dump() for x in getattr(body, "pins", [])]


async def _subjects(p: dict):
    subs = await pitch.subjects_of(p)
    if not subs:
        raise HTTPException(404, "Every name in this brief is new to Qloo.")
    return subs, [s["entity"]["entity_id"] for s in subs], subs[0]["type"], [s["entity"]["name"] for s in subs]


async def _spend(counter: str = "pitch_write", cap: int = WRITE_DAY):
    if not await cache.spend(counter, cap):
        raise HTTPException(429, "Room has pitched its share for today. The three samples still open with their first pitch.")


async def _brief(text: str) -> dict:
    return await pitch.brief_cached(text)


async def _keep(sample: str, p: dict) -> bool:
    """A result goes to the shared cache only when the request is a built-in sample, untouched (any age band)."""
    if not sample or sample not in pitch.SAMPLES:
        return False
    return pitch.same_sample(p, await _brief(pitch.SAMPLES[sample]))


def _core(ideas: list) -> list:
    """An idea as the writer made it, for matching a posted idea with the sample's own."""
    out = []
    for i in ideas:
        d = i if isinstance(i, dict) else i.model_dump()
        out.append({"title": d.get("title"), "line": d.get("line"), "insight": d.get("insight"), "idea": d.get("idea"),
                    "slots": {k: (v or {}).get("id") for k, v in (d.get("slots") or {}).items()},
                    "lead_city": d.get("lead_city")})
    return out


async def _is_sample_ideas(sample: str, p: dict, ideas: list) -> bool:
    """Posted ideas count as the sample's only when they are its first-round ideas, word for word."""
    if not await _keep(sample, p):
        return False
    w = await cache.get(Cache.key("pitch_write", p, llm.MODEL, 3))
    return bool(w) and _core(w["ideas"])[:len(ideas)] == _core(ideas)


@app.post("/api/pitch/brief")
async def pitch_brief(body: PitchBriefIn, request: Request):
    """Gemini reads the line; Qloo resolves every name in it."""
    limit(request, 10)
    if not pitch.sample_of(body.text):
        hit = await cache.get(Cache.key("pitch_brief", body.text.strip(), llm.MODEL, 3))
        if not hit:
            _cap("brief")
            await _spend("pitch_read", READ_DAY)
    return await _brief(body.text)


@app.post("/api/pitch/lane")
async def pitch_lane(body: PitchLaneIn, request: Request):
    """One kind of culture these fans love, ranked by lift against the control's fans."""
    limit(request, 60)
    p = _pitch(body)
    if body.lane not in dict(pitch.LANES):
        raise HTTPException(400, "Unknown lane.")
    _cap("qloo")
    _, ids, lead, names = await _subjects(p)
    return pitch.lane_public(await pitch.lane(ids, body.lane, lead, p["age"], names))


@app.post("/api/pitch/threads")
async def pitch_threads(body: PitchParams, request: Request):
    limit(request, 12)
    p = _pitch(body)
    _cap("qloo")
    subs, ids, lead, names = await _subjects(p)
    ls = await pitch.lanes(ids, lead, p["age"], names)
    marks = await pitch.marks(pitch.launching_brand(subs), [r for l in ls for r in l["rows"][:12]])
    return {"threads": await pitch.threads(ls, p["age"]), "marks": marks}


@app.post("/api/pitch/where")
async def pitch_where(body: PitchParams, request: Request):
    """Room's own map of the subject, city by city, with a role for each."""
    limit(request, 12)
    p = _pitch(body)
    _cap("qloo")
    subs, *_ = await _subjects(p)
    return await pitch.where(subs, p["cities"], p["age"])


@app.post("/api/pitch/venues")
async def pitch_venues(body: PitchCityIn, request: Request):
    limit(request, 30)
    p = _pitch(body)
    _cap("qloo")
    _, ids, lead, _ = await _subjects(p)
    try:
        return await pitch.venues(ids, body.city.strip(), p["categories"], p["kind"], p["age"], lead)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/pitch/write")
async def pitch_write(body: PitchWriteIn, request: Request):
    """Up to three ideas from the evidence pack. Every slot is an id the server holds; every name renders from Qloo."""
    limit(request, 6)
    p = _pitch(body)
    first = body.seed == 0 and not (body.kept or body.killed or body.answer or body.tone or body.pins)
    key = Cache.key("pitch_write", p, llm.MODEL, 3)
    if first and (hit := await cache.get(key)):
        return hit
    keep = first and await _keep(body.sample, p)
    _cap("write")
    if not keep:
        await _spend()
    try:
        out = await pitch.write(p, body.kept, body.killed, body.answer, _pins(body), body.tone)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if first and out["ideas"]:
        await cache.set(key, out, keep=keep)
    return out


@app.post("/api/pitch/readback")
async def pitch_readback(body: PitchIdeasIn, request: Request):
    """Room's script reader reads the ideas back against the pack."""
    limit(request, 8)
    p = _pitch(body)
    ideas = [i.model_dump() for i in body.ideas]
    key = Cache.key("pitch_readback", p, _core(ideas), _pins(body), llm.MODEL, 3)
    if hit := await cache.get(key):
        return hit
    sample = await _is_sample_ideas(body.sample, p, ideas) and not body.pins
    _cap("readback")
    if not sample:
        await _spend()
    out = await pitch.readback(p, ideas, _pins(body))
    if out["ideas"] and not out["tally"]["stalled"]:
        await cache.set(key, out, keep=sample)
    return out


@app.post("/api/pitch/strip")
async def pitch_strip(body: PitchItemIn, request: Request):
    limit(request, 30)
    p = _pitch(body)
    _cap("qloo")
    try:
        return await pitch.strip(p, body.id, _pins(body))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/pitch/whatif")
async def pitch_whatif(body: PitchWhatIfIn, request: Request):
    limit(request, 12)
    p = _pitch(body)
    await _subjects(p)
    _cap("whatif")
    await _spend("pitch_read", READ_DAY)
    try:
        return await pitch.whatif(p, body.text)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/pitch/rollout")
async def pitch_rollout(body: PitchIdeaIn, request: Request):
    limit(request, 6)
    p = _pitch(body)
    idea = body.idea.model_dump()
    key = Cache.key("pitch_rollout", p, _core([idea]), _pins(body), llm.MODEL, 3)
    if hit := await cache.get(key):
        return hit
    sample = await _is_sample_ideas(body.sample, p, [idea]) if not body.pins else False
    _cap("rollout")
    if not sample:
        await _spend()
    out = await pitch.rollout(p, idea, _pins(body))
    if out["beats"] and not out["stalled"]:
        await cache.set(key, out, keep=sample)
    return out


DRAW_PER_HOUR = 6      # per visitor
DRAW_INSTANCE_HOUR = 30
DRAW_DAY = 100
_draw_hits: dict[str, list[float]] = {}
_draw_all: list[float] = []
_draw_jobs = asyncio.Semaphore(2)


@app.post("/api/pitch/draw")
async def pitch_draw(body: PitchIdeaIn, request: Request):
    """A key visual for one idea, described only in Room's words (roles, rooms, mood), then read back in the browser."""
    limit(request, 2)
    p = _pitch(body)
    idea = body.idea.model_dump()
    key = Cache.key("pitch_draw", p, _core([idea]), _pins(body), 3)
    if hit := await cache.get(key):
        return hit
    sample = await _is_sample_ideas(body.sample, p, [idea]) if not body.pins else False
    now = time.time()
    ip = client_ip(request)
    mine = [t for t in _draw_hits.get(ip, []) if now - t < 3600]
    _draw_all[:] = [t for t in _draw_all if now - t < 3600]
    if not sample:
        if len(mine) >= DRAW_PER_HOUR:
            raise HTTPException(429, "Room draws six key visuals an hour per visitor.")
        if len(_draw_all) >= DRAW_INSTANCE_HOUR:
            raise HTTPException(429, "Room is drawing for a crowd. Try again in a few minutes.")
        if not await cache.spend("draw", DRAW_DAY):
            raise HTTPException(429, "Room has drawn its share of key visuals for today. The samples still draw.")
        _draw_hits[ip] = mine + [now]
        _draw_all.append(now)
    async with _draw_jobs:
        try:
            out = await asyncio.wait_for(pitch.draw(p, idea, _pins(body)), 56)
        except asyncio.TimeoutError:
            raise HTTPException(504, "The drawing took too long. Try again.")
        except ValueError as e:
            raise HTTPException(404, str(e))
        except RuntimeError as e:
            raise HTTPException(502, str(e))
    await cache.set(key, out, keep=sample)
    return out


@app.get("/api/search")
async def search(q: str, request: Request, type: str | None = None):
    limit(request, 30)
    return {"results": await engine.search(q[:120], type)}


@app.get("/api/city")
async def city(q: str):
    return await engine.city(q)


WEB = Path(__file__).parent.parent / "web"
if os.environ.get("ROOM_SERVE_WEB") and WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
