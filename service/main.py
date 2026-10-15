"""Room API. Hosting rewrites /api/** here; locally it also serves ../web."""

import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import agent  # noqa: E402
import engine  # noqa: E402
from cache import cache, Cache  # noqa: E402
import llm  # noqa: E402
from qloo import QlooError  # noqa: E402

app = FastAPI(title="Room")

MAX_TEXT = 6000
MAX_CITIES = 4
READ_VERSION = 4  # bump when the extraction prompt changes

# ---------- light per-IP limiter: the demo spends a shared key ----------
_hits: dict[str, list[float]] = {}


def limit(request: Request, per_min: int):
    """Per IP and per endpoint, so a read and its dozen score calls count separately."""
    ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
    key = f"{ip}|{request.url.path}"
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < 60]
    if len(recent) >= per_min:
        raise HTTPException(429, "Easy. Give the room a minute.")
    recent.append(now)
    _hits[key] = recent


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

    out = await asyncio.gather(*[match(r) for r in refs[:30]])
    for i, r in enumerate(out):
        r["id"] = f"r{i}"
    result = {"references": out}
    if out:
        await cache.set(Cache.key("read", body.text, llm.MODEL, READ_VERSION), result)
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


# ---------- the rewrite agent: one short step per request ----------

class AgentPlanIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    refs: list[dict] = Field(max_length=30)
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
    limit(request, 30)
    return await agent.find(body.ref, body.city, body.exclude)


class AgentTestIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    refs: list[dict] = Field(max_length=30)
    ref_id: str
    picks: list[dict] = Field(max_length=3)
    city: str
    cities: list[str] = Field(min_length=1, max_length=MAX_CITIES)
    age: str | None = None


@app.post("/api/agent/test")
async def agent_test(body: AgentTestIn, request: Request):
    limit(request, 30)
    check_age(body.age)
    return await agent.test(body.text, body.refs, body.ref_id, body.picks, body.city, body.cities, body.age)


@app.get("/api/search")
async def search(q: str, type: str | None = None):
    return {"results": await engine.search(q, type)}


@app.get("/api/city")
async def city(q: str):
    return await engine.city(q)


WEB = Path(__file__).parent.parent / "web"
if os.environ.get("ROOM_SERVE_WEB") and WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
