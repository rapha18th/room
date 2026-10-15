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

import engine  # noqa: E402
from cache import cache, Cache  # noqa: E402
import llm  # noqa: E402
from qloo import QlooError  # noqa: E402

app = FastAPI(title="Room")

MAX_TEXT = 6000
MAX_CITIES = 4

# ---------- light per-IP limiter: the demo spends a shared key ----------
_hits: dict[str, list[float]] = {}


def limit(request: Request, per_min: int):
    ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
    now = time.time()
    recent = [t for t in _hits.get(ip, []) if now - t < 60]
    if len(recent) >= per_min:
        raise HTTPException(429, "Easy. Give the room a minute.")
    recent.append(now)
    _hits[ip] = recent


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
    hit = await cache.get(Cache.key("read", body.text, llm.MODEL))
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
        await cache.set(Cache.key("read", body.text, llm.MODEL), result)
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


@app.get("/api/search")
async def search(q: str, type: str | None = None):
    return {"results": await engine.search(q, type)}


@app.get("/api/city")
async def city(q: str):
    return await engine.city(q)


WEB = Path(__file__).parent.parent / "web"
if os.environ.get("ROOM_SERVE_WEB") and WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
