"""The rewrite agent: make a script land with one city's audience.

The browser drives the loop one short step at a time, so every step fits Hosting's 60 s window
and the trace streams in as it happens:

  plan  Gemini reads the script and the room's verdicts, then decides which weak references
        to swap and which to keep (a reference stays when its foreignness is the point).
  find  Qloo returns what this audience has affinity for; Gemini keeps the picks that do the
        same job in the line and rewrites it.
  test  Qloo scores every pick in the same room; the best one that lands goes into the script.

Each step returns trace entries naming who acted (gemini, qloo, room), what they did, and how long it took.
"""

import asyncio
import time

from pydantic import BaseModel, Field

import engine
import llm

TARGET = 90  # room score the agent works toward in its city
WEAK = {"dies", "inside", "unscored"}
GOOD = {"lands", "roast", "famous", "global"}


def verdict_of(ref: dict, city: str):
    if ref.get("outside") or not ref.get("match"):
        return None
    return (((ref.get("score") or {}).get("cities") or {}).get(city) or {}).get("verdict")


def room_score(refs: list[dict], city: str):
    vals = [engine.VALUE[v] for r in refs if (v := verdict_of(r, city)) in engine.VALUE]
    return round(100 * sum(vals) / len(vals)) if vals else None


def entry(who: str, text: str, t0: float | None = None, **extra) -> dict:
    e = {"who": who, "text": text, **extra}
    if t0 is not None:
        e["ms"] = int((time.time() - t0) * 1000)
    return e


# ---------- plan ----------

class Step(BaseModel):
    ref_id: str
    action: str = Field(description="swap or keep")
    why: str = Field(description="One short sentence the writer will read")


class Plan(BaseModel):
    thinking: str = Field(description="One or two sentences on the room and the approach")
    steps: list[Step]


PLAN = """You are tuning a script for a live audience in {city}. Qloo's taste graph has scored every
cultural reference for that audience.

SCRIPT:
{text}

REFERENCES (id | reference | its job in the line | verdict in {city} | verdicts elsewhere):
{rows}

Verdicts: lands = known and loved; roast = known, kept at a distance; famous = known everywhere;
inside = a slice of the room knows it; dies = a blank for most of the room.

For every reference that dies or sits inside in {city}, decide: swap it for something this audience
knows, or keep it. Keep a reference when its foreignness is the point of the line: it belongs to a
character from somewhere else, or the joke is that nobody knows it. Put the swaps that lift the room
most first. Leave references that land, roast or are famous out of the plan.
"""


async def plan(text: str, refs: list[dict], city: str) -> dict:
    trace, t0 = [], time.time()
    weak = [r for r in refs if verdict_of(r, city) in WEAK]
    before = room_score(refs, city)
    trace.append(entry("room", f"{city} sits at {before}%. {len(weak)} of {len(refs)} references are weak there."))
    if not weak:
        trace.append(entry("room", f"Everything already has a pulse in {city}."))
        return {"plan": [], "trace": trace, "before": before}

    rows = "\n".join(
        f"{r['id']} | {r['surface']} | {r.get('role', '')} | {verdict_of(r, city) or 'unscored'} | "
        + ", ".join(f"{c}: {v.get('verdict')}" for c, v in ((r.get('score') or {}).get('cities') or {}).items() if c != city)
        for r in refs if not r.get("outside") and r.get("match")
    )
    parsed = await llm.generate(PLAN.format(city=city, text=text, rows=rows), Plan, 0.2)
    ids = {r["id"]: r for r in weak}
    steps = [s for s in (parsed.steps if parsed else []) if s.ref_id in ids]
    trace.append(entry("gemini", parsed.thinking if parsed else "Planned the pass.", t0, kind="plan"))
    for s in steps:
        r = ids[s.ref_id]
        trace.append(entry("gemini", f"{'Swap' if s.action == 'swap' else 'Keep'} {r['surface']}. {s.why}",
                           kind=s.action, ref_id=s.ref_id))
    return {"plan": [s.model_dump() for s in steps], "trace": trace, "before": before}


# ---------- find ----------

async def find(ref: dict, city: str, exclude: list[str]) -> dict:
    trace, t0 = [], time.time()
    cands = await engine.swap_candidates(ref["match"], ref["type"], city, set(exclude))
    trace.append(entry("qloo", f"/v2/insights · {len(cands)} {ref['type'].replace('_', ' ')}s with affinity in {city}, "
                       f"by taste similarity to {ref['match']['name']} and by its genre tags", t0, kind="call"))
    if not cands:
        return {"picks": [], "trace": trace}
    t1 = time.time()
    picks = await llm.pick_swaps(ref["sentence"], ref["surface"], ref.get("role", ""), city, cands)
    names = ", ".join(p["candidate"]["name"] for p in picks) or "none"
    trace.append(entry("gemini", f"Kept the ones that do the same job: {names}.", t1, kind="pick"))
    return {"picks": picks, "trace": trace}


# ---------- test and apply ----------

def swap_span(old: str, new: str, name: str):
    i = new.lower().find(name.lower())
    if i >= 0:
        return i, len(name)
    p = 0
    while p < len(old) and p < len(new) and old[p] == new[p]:
        p += 1
    q = 0
    while q < len(old) - p and q < len(new) - p and old[-1 - q] == new[-1 - q]:
        q += 1
    while p > 0 and new[p - 1].isalnum():
        p -= 1
    while q > 0 and new[len(new) - q].isalnum():
        q -= 1
    changed = new[p:len(new) - q].strip()
    if not changed:
        return None
    return new.find(changed, p), len(changed)


def apply(text: str, refs: list[dict], ref_id: str, pick: dict, score: dict):
    ref = next(r for r in refs if r["id"] == ref_id)
    old, new = ref["sentence"], pick["line"]
    at = text.rfind(old, 0, ref["start"] + 1)
    if at < 0:
        at = text.find(old)
    if at < 0:
        return None
    end = at + len(old)
    delta = len(new) - len(old)
    out = text[:at] + new + text[end:]
    span = swap_span(old, new, pick["candidate"]["name"])
    updated = []
    for r in refs:
        r = dict(r)
        if r["id"] == ref_id:
            s, n = span if span else (0, len(new))
            r.update(surface=new[s:s + n], name=pick["candidate"]["name"], match=pick["candidate"],
                     candidates=[pick["candidate"]], certain=True, start=at + s, end=at + s + n,
                     sentence=new, score=score, swapped_from=ref["surface"])
        elif r["end"] <= at:
            pass
        elif r["start"] >= end:
            r["start"] += delta
            r["end"] += delta
        else:
            j = out.find(r["surface"], at, at + len(new))
            if j >= 0:
                r["start"], r["end"] = j, j + len(r["surface"])
            r["sentence"] = new
        updated.append(r)
    return out, updated


async def test(text: str, refs: list[dict], ref_id: str, picks: list[dict], city: str,
               cities: list[str], age: str | None) -> dict:
    trace, t0 = [], time.time()
    ref = next(r for r in refs if r["id"] == ref_id)
    current = engine.VALUE.get(verdict_of(ref, city), 0)
    scores = await asyncio.gather(*[engine.score(p["candidate"], ref["type"], cities, age) for p in picks],
                                  return_exceptions=True)
    best, best_val = None, current
    for p, s in zip(picks, scores):
        if isinstance(s, Exception):
            trace.append(entry("qloo", f"{p['candidate']['name']}: scoring failed", kind="call"))
            continue
        d = (s.get("cities") or {}).get(city) or {}
        v = d.get("verdict", "unscored")
        trace.append(entry("qloo", f"heatmap · {p['candidate']['name']} in {city}: {v} "
                           f"(known {d.get('known', 0):.2f}, loved {d.get('loved') if d.get('loved') is not None else 'n/a'})",
                           kind="call", verdict=v))
        val = engine.VALUE.get(v, 0)
        if val > best_val:
            best, best_val = (p, s), val
    if not best:
        trace.append(entry("room", f"Nothing beats {ref['surface']} in {city}. Keeping it.", t0, kind="keep"))
        return {"applied": False, "text": text, "refs": refs, "trace": trace}
    p, s = best
    done = apply(text, refs, ref_id, p, s)
    if not done:
        trace.append(entry("room", "That line changed under the agent. Skipping it.", kind="keep"))
        return {"applied": False, "text": text, "refs": refs, "trace": trace}
    out, updated = done
    trace.append(entry("room", f"{ref['surface']} → {p['candidate']['name']}: “{p['line']}”", t0, kind="edit",
                       ref_id=ref_id, before=ref["surface"], after=p["candidate"]["name"]))
    trace.append(entry("room", f"{city} now at {room_score(updated, city)}%.", kind="score"))
    return {"applied": True, "text": out, "refs": updated, "trace": trace}
