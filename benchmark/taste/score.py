"""Sections 7 to 9: score every system once and name the outcome.

Reads the public items and identity files and the private system outputs. Writes the public pick file
(one row per item: every system's score on it, its cluster and populations, no Qloo values) and results_<snap>.json.

Primary metric (8.3 with 12.19): cluster macro accuracy with pair balancing. Each cluster weighs 1, split equally
over its items; within each city pair the two directions are then rescaled to equal total weight, so any fixed
per-pair predictor scores exactly 50% (4.5). The plain cluster macro is reported beside it.

Usage: python benchmark/taste/score.py dev|eval [--stub] [--allow-missing]
"""

import collections
import itertools
import json
import math
import statistics
import sys

import numpy as np

from common import (DATA, GROUPS, POPULATION, PRIVATE, SEED, WITHIN, dump, label, load, preset, sha_order)

SNAP = sys.argv[1]
STUB = "--stub" in sys.argv
RUN = PRIVATE / SNAP / ("stub" if STUB else "run")
LLM = ["S3L", "S3K", "S4"]
NULLS = ["N1", "N2", "N3", "N4"]
CONFIRM = ["S1"] + LLM + NULLS
EXPLORE = ["R1", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10", "E11", "E12", "E13"]
SYSTEMS = CONFIRM + EXPLORE
B = 10_000


# ---------- loading ----------

def heat(tag):
    p = RUN / "heatmaps" / f"{tag}.json"
    return load(p) if p.exists() else None


def heat_at(run, tag):
    p = run / "heatmaps" / f"{tag}.json"
    return load(p) if p.exists() else None


def gemini_rows():
    rows = []
    for name in ("gemini.jsonl", "gemini_extra.jsonl"):
        p = RUN / name
        if p.exists():
            rows += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


# ---------- per-city keys ----------

def s1_key(agg, base, city, decimals=4, field="median"):
    """(Loved defined, Loved, ratio): engine.score's home key with the 5-cell gate (6, S1)."""
    a = (agg or {}).get("cities", {}).get(preset(city)) or {}
    b = (base or {}).get("cities", {}).get(preset(city)) or {}
    cells = a.get("cells", 0)
    val = a.get(field)
    loved = round(val, decimals) if (val is not None and cells >= 5) else None
    ratio = cells / max(1, b.get("cells", 0))
    return (loved is not None, loved or 0.0, ratio)


def cmp(ka, kb):
    return 1.0 if ka > kb else 0.0 if ka < kb else 0.5


def circle_agg(rec, km=20.0):
    """E13: per city, the cells within 20 km of the city's centre."""
    out = {}
    for c in rec["room"]:
        vals = []
        for x in rec["cells"]:
            loc = x.get("location") or {}
            dlat = (loc.get("latitude", 0) - c["lat"]) * 111.0
            dlon = (loc.get("longitude", 0) - c["lon"]) * 111.0 * math.cos(math.radians(c["lat"]))
            if math.hypot(dlat, dlon) <= km and (x.get("query") or {}).get("affinity") is not None:
                vals.append(x["query"]["affinity"])
        out[c["name"]] = {"cells": len(vals), "median": round(statistics.median(vals), 4) if vals else None}
    return {"cities": out}


def avg_ranks(keys: dict) -> dict:
    """Rank 1 = best; tied keys share the mean of their positions."""
    order = sorted(keys, key=lambda c: keys[c], reverse=True)
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and keys[order[j + 1]] == keys[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


# ---------- populations ----------

def pair_of(it):
    return (it["group"], tuple(sorted([it["gold"], it["other"]])))


def balance(items):
    """4.5: within each unordered city pair keep min(n_A, n_B) items in each direction, by ascending sha1."""
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for it in items:
        by[pair_of(it)][it["gold"]].append(it)
    out = []
    for p, dirs in by.items():
        if len(dirs) < 2:
            continue
        k = min(len(v) for v in dirs.values())
        for gold, v in dirs.items():
            out += sorted(v, key=lambda i: sha_order(i["artist_id"], i["gold"], i["other"]))[:k]
    return out


def covered_set(items, res, identity, grp_heat):
    """5.3: a certain match that passed the identity check and has a group-polygon map with at least one cell."""
    out = set()
    for g, aid in {(i["group"], i["artist_id"]) for i in items}:
        r, rec = res.get(aid) or {}, grp_heat(g, aid)
        if r.get("certain") and identity.get(aid) == "pass" and rec and rec["total"] >= 1:
            out.add((g, aid))
    return out


def populations_full(items):
    """7.1 and 7.2. Items carry 'covered'. Returns (populations, coverage per group, P1 pool)."""
    groups = sorted({i["group"] for i in items})
    elig, cov = collections.defaultdict(set), collections.defaultdict(set)
    for it in items:
        elig[it["group"]].add(it["artist_id"])
        if it["covered"]:
            cov[it["group"]].add(it["artist_id"])
    coverage = {g: len(cov[g]) / max(1, len(elig[g])) for g in groups}
    pool = [g for g in WITHIN if g in groups and coverage[g] >= 0.6]
    pops = {"P1": balance([i for i in items if i["group"] in pool and i["covered"]]),
            "P2": balance([i for i in items if i["group"] in WITHIN]),
            "africa": balance([i for i in items if i["group"] == "africa" and i["covered"]])}
    for g in WITHIN:
        if g in groups and g not in pool:
            pops[f"below_floor_{g}"] = balance([i for i in items if i["group"] == g and i["covered"]])
    return pops, coverage, pool


def populations(items):
    return populations_full(items)[0]


def pair_tag(it, kind="pair"):
    a, b = sorted([it["gold"], it["other"]])
    return f"{kind}_{it['group']}_{it['artist_id']}_{a}_{b}" if kind == "pair" else f"{kind}_{it['group']}_{a}_{b}"


def clusters(items, maps):
    """8.2: one cluster per Apple artist ID; artists in one group whose group maps nearly coincide merge
    (cell-set Jaccard above 0.9, and common affinities identical or Spearman above 0.9)."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_group = collections.defaultdict(set)
    for it in items:
        by_group[it["group"]].add(it["artist_id"])
        find(it["artist_id"])
    shared = set()
    for g, ids in by_group.items():
        sig = {}
        for aid in ids:
            rec = maps.get((g, aid))
            if rec and rec["cells"]:
                sig[aid] = {(x.get("location") or {}).get("geohash") or f"{x['location']['latitude']:.3f},{x['location']['longitude']:.3f}":
                            (x.get("query") or {}).get("affinity") for x in rec["cells"]}
        for a, b in itertools.combinations(sorted(sig), 2):
            sa, sb = set(sig[a]), set(sig[b])
            common = sorted(sa & sb)
            if not common or len(common) / len(sa | sb) <= 0.9:
                continue
            va, vb = [sig[a][k] for k in common], [sig[b][k] for k in common]
            if va == vb or spearman(va, vb) > 0.9:
                parent[find(a)] = find(b)
                shared.update([a, b])
    return {aid: find(aid) for aid in parent}, shared


def spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(x) < 2:
        return 0.0
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


# ---------- statistics (8.3 to 8.5) ----------

class Pop:
    """A population as arrays: cluster, city pair and direction per item, and every system's item scores."""

    def __init__(self, items, cl, systems=SYSTEMS):
        self.items, self.systems = items, systems
        ck = {k: n for n, k in enumerate(sorted({cl[i["artist_id"]] for i in items}))}
        pk = {k: n for n, k in enumerate(sorted({pair_of(i) for i in items}))}
        dk = {k: n for n, k in enumerate(sorted({(pair_of(i), i["gold"]) for i in items}))}
        self.c = np.array([ck[cl[i["artist_id"]]] for i in items], dtype=int)
        self.p = np.array([pk[pair_of(i)] for i in items], dtype=int)
        self.d = np.array([dk[(pair_of(i), i["gold"])] for i in items], dtype=int)
        self.nc, self.np_, self.nd = len(ck), len(pk), len(dk)
        self.size = np.bincount(self.c, minlength=self.nc).astype(float)
        self.S = np.array([[i["picks"][s] for s in systems] for i in items], dtype=float)
        self.col = {s: k for k, s in enumerate(systems)}

    def weights(self, cmult=None, pmult=None, balanced=True):
        cm = np.ones(self.nc) if cmult is None else cmult
        w = cm[self.c] / self.size[self.c]
        if pmult is not None:
            w = w * pmult[self.p]
        if not balanced:
            return w
        wd = np.bincount(self.d, w, minlength=self.nd)
        wp = np.bincount(self.p, w, minlength=self.np_)
        f = np.divide(wp[self.p] / 2, wd[self.d], out=np.zeros_like(w), where=wd[self.d] > 0)
        return w * f

    def score(self, w=None):
        w = self.weights() if w is None else w
        tot = w.sum()
        return dict(zip(self.systems, (w @ self.S) / tot)) if tot > 0 else {s: float("nan") for s in self.systems}

    def bootstrap(self, diffs, seed=SEED, pairs=False, n=B):
        """Percentile 95% intervals and one-sided 5% / 95% bounds, for every system and each (a, b) difference."""
        rng = np.random.default_rng(seed + (1 if pairs else 0))
        draws = np.empty((n, len(self.systems)))
        for k in range(n):
            if pairs:
                w = self.weights(pmult=np.bincount(rng.integers(0, self.np_, self.np_), minlength=self.np_).astype(float))
            else:
                w = self.weights(cmult=np.bincount(rng.integers(0, self.nc, self.nc), minlength=self.nc).astype(float))
            tot = w.sum()
            draws[k] = (w @ self.S) / tot if tot > 0 else np.nan
        q = lambda v: {"lo": float(np.nanpercentile(v, 2.5)), "hi": float(np.nanpercentile(v, 97.5)),
                       "lo5": float(np.nanpercentile(v, 5)), "hi95": float(np.nanpercentile(v, 95))}
        out = {s: q(draws[:, self.col[s]]) for s in self.systems}
        for a, b in diffs:
            out[f"{a}-{b}"] = q(draws[:, self.col[a]] - draws[:, self.col[b]])
        return out

    def sign_flip(self, a, b, seed=SEED):
        """One-sided paired sign-flip permutation test on per-cluster contributions to the weighted difference;
        H1: a > b. Exact at 16 clusters or fewer."""
        w = self.weights()
        if w.sum() <= 0:
            return 1.0
        dvec = np.bincount(self.c, w * (self.S[:, self.col[a]] - self.S[:, self.col[b]]), minlength=self.nc) / w.sum()
        obs = dvec.sum()
        if self.nc <= 16:
            signs = np.array(list(itertools.product([1, -1], repeat=self.nc)))
            return float(np.mean(signs @ dvec >= obs - 1e-12))
        rng = np.random.default_rng(seed)
        sims = rng.choice([-1.0, 1.0], size=(B, self.nc)) @ dvec
        return float((np.sum(sims >= obs - 1e-12) + 1) / (B + 1))

    def plain_macro(self):
        """The original 8.3: mean over clusters of each cluster's mean item score."""
        w = self.weights(balanced=False)
        return dict(zip(self.systems, (w @ self.S) / w.sum()))


def holm(ps: dict) -> dict:
    order = sorted(ps, key=ps.get)
    out, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (len(order) - i) * ps[k]))
        out[k] = running
    return out


# ---------- picks ----------

def main():
    items_doc = load(DATA / f"items_{SNAP}.json")
    res = load(PRIVATE / SNAP / "resolution.json") if (PRIVATE / SNAP / "resolution.json").exists() else {}
    idp = DATA / f"identity_{SNAP}.json"
    if idp.exists():
        identity = load(idp)["verdicts"]
    elif SNAP == "dev" or STUB:
        identity = {a: "pass" for a in res}
    else:
        raise SystemExit(f"{idp.name} is missing: the blind identity check (5.2) must run before scoring")
    items = [dict(i) for i in items_doc["items"]]
    groups = sorted({i["group"] for i in items})

    maps = {(i["group"], i["artist_id"]): heat(f"grp_{i['group']}_{i['artist_id']}") for i in items}   # group polygon
    base = {g: heat(f"basegrp_{g}") for g in groups}
    panel = load(RUN / "n4_panel.json") if (RUN / "n4_panel.json").exists() else {}
    n4 = {}
    for g, arts in panel.items():
        per = collections.defaultdict(list)
        for a in arts:
            rec = heat(f"n4_{g}_{a['artist_id']}")
            for c, v in ((rec or {}).get("aggregate") or {}).get("cities", {}).items():
                if v["cells"] >= 5 and v["median"] is not None:
                    per[c].append(v["median"])
        n4[g] = {c: statistics.median(v) for c, v in per.items()}

    covered = covered_set(items, res, identity, lambda g, a: maps.get((g, a)))

    gem = collections.defaultdict(list)
    failures = collections.Counter()
    for r in gemini_rows():
        if "key" not in r:
            continue
        k = (r["system"], r["key"][0], r["key"][1])
        if "out" in r:
            gem[k].append(r)
        else:
            failures[r["system"]] += 1

    # R1 oracle: leads per genre on each city's chart, from the iTunes genre lookups.
    looks = load(PRIVATE / "lookups" / "itunes_artists.json") if (PRIVATE / "lookups" / "itunes_artists.json").exists() else {}
    snap = load(DATA / ("charts_dev_20261015.json" if SNAP == "dev" else "charts_eval.json"))
    from build import lead_of
    chart_leads = {c: [lead_of(e, "in" if c in GROUPS["in"] else "us") for e in ch["entries"]]
                   for c, ch in snap["apple_city"].items()}

    def s4_mean_rank(sysname, g, aid, city):
        """Mean rank over the answered runs; S4 needs at least one answer in each city order (6, review 5)."""
        rows = gem.get((sysname, g, aid)) or []
        if sysname in ("S4", "E11") and not ({r["key"][3] for r in rows} >= {"alpha", "reverse"}):
            return None
        ranks = [r["out"]["rank"][label(city)] for r in rows]
        return statistics.fmean(ranks) if ranks else None

    live = {g: [c for c in GROUPS[g] if any(c in (i["gold"], i["other"]) for i in items if i["group"] == g)] for g in groups}

    # N3 (12.9 as amended): each city's win rate over the group's eligible items with the item's whole city pair
    # left out, so the prior is fixed per pair.
    wins, apps, pw, pa = (collections.Counter() for _ in range(4))
    for x in items:
        wins[(x["group"], x["gold"])] += 1
        for c in (x["gold"], x["other"]):
            apps[(x["group"], c)] += 1
        pw[(pair_of(x), x["gold"])] += 1
        pa[pair_of(x)] += 1

    def n3_rate(it, c):
        p = pair_of(it)
        w = wins[(it["group"], c)] - pw[(p, c)]
        n = apps[(it["group"], c)] - pa[p]
        return w / n if n > 0 else 0.5

    for it in items:
        g, aid, A, Bc = it["group"], it["artist_id"], it["gold"], it["other"]
        grec, gbs = maps.get((g, aid)), base.get(g)                       # group polygon: E7, E9
        rec, bs = heat(pair_tag(it)), heat(pair_tag(it, "basepair"))      # per-pair room: S1 (5.4)
        agg, bagg = (rec or {}).get("aggregate"), (bs or {}).get("aggregate")
        cov = (g, aid) in covered
        it["covered"] = cov
        it["pair_map"] = rec is not None and bs is not None
        cov_pair = cov and it["pair_map"]
        p = {}
        p["S1"] = cmp(s1_key(agg, bagg, A), s1_key(agg, bagg, Bc)) if cov_pair else 0.5
        s3 = (gem.get(("S3", g, aid)) or [None])[0]
        if s3:
            ga, gb = s3["out"][label(A)], s3["out"][label(Bc)]
            p["S3L"] = cmp((ga["loved"], ga["known"]), (gb["loved"], gb["known"]))
            p["S3K"] = cmp((ga["known"] * ga["loved"], ga["known"]), (gb["known"] * gb["loved"], gb["known"]))
        else:
            p["S3L"] = p["S3K"] = 0.5
        ra, rb = s4_mean_rank("S4", g, aid, A), s4_mean_rank("S4", g, aid, Bc)
        p["S4"] = 0.5 if ra is None else cmp(-ra, -rb)
        p["N1"] = cmp(POPULATION[A], POPULATION[Bc])
        nb = bagg if bs is not None else (gbs or {}).get("aggregate")
        p["N2"] = cmp(s1_key(nb, nb, A), s1_key(nb, nb, Bc))
        p["N3"] = cmp(n3_rate(it, A), n3_rate(it, Bc))
        nv = n4.get(g, {})
        p["N4"] = cmp((preset(A) in nv, nv.get(preset(A), 0)), (preset(Bc) in nv, nv.get(preset(Bc), 0)))
        genre = it.get("genre")
        cnt = lambda c: sum(1 for ld in chart_leads.get(c, []) if ld and ld["apple_id"] != aid and genre
                            and (looks.get(ld["apple_id"]) or {}).get("genre") == genre)
        p["R1"] = cmp(cnt(A), cnt(Bc))
        gagg, gbase = (grec or {}).get("aggregate"), (gbs or {}).get("aggregate")
        if cov_pair:
            ca = lambda c, f: ((agg["cities"].get(preset(c)) or {}).get(f))
            gate = lambda c, f: (ca(c, f) is not None and ca(c, "cells") >= 5, ca(c, f) or 0.0)
            ka, kb = s1_key(agg, bagg, A), s1_key(agg, bagg, Bc)
            p["E1"] = cmp(ka[2], kb[2])
            p["E2"] = cmp(gate(A, "popularity"), gate(Bc, "popularity"))
            p["E3"] = cmp(gate(A, "p75"), gate(Bc, "p75"))
            p["E4"] = cmp(gate(A, "rank"), gate(Bc, "rank"))
            p["E5"] = cmp(s1_key(agg, bagg, A, 2), s1_key(agg, bagg, Bc, 2))
            p["E6"] = 0.5 if not (ka[0] and kb[0]) else cmp(ka, kb)
            ci, cb = circle_agg(rec), circle_agg(bs)
            p["E13"] = cmp(s1_key(ci, cb, A), s1_key(ci, cb, Bc))
        else:
            for e in ("E1", "E2", "E3", "E4", "E5", "E6", "E13"):
                p[e] = 0.5
        if cov and gagg:
            # E7 on the group map, the same room as N4's panel medians (review 23).
            dm = lambda c: (lambda k: (k[0], k[1] - nv.get(preset(c), 0.0), k[2]))(s1_key(gagg, gbase, c))
            p["E7"] = cmp(dm(A), dm(Bc))
        else:
            p["E7"] = 0.5
        p["E8"] = p["S1"] if cov else p["S3L"]
        r1 = None
        if cov and gagg:
            keys = {c: s1_key(gagg, gbase, c) for c in live[g]}
            r1 = avg_ranks(keys) if len(set(keys.values())) > 1 else None
        r4 = {c: s4_mean_rank("S4", g, aid, c) for c in live[g]}
        if r4.get(A) is None:
            p["E9"] = 0.5
        elif r1 is None:
            p["E9"] = cmp(-r4[A], -r4[Bc])
        else:
            p["E9"] = cmp(-(0.5 * r1[A] + 0.5 * r4[A]), -(0.5 * r1[Bc] + 0.5 * r4[Bc]))
        for e in ("E10", "E11"):
            ea, eb = s4_mean_rank(e, g, aid, A), s4_mean_rank(e, g, aid, Bc)
            p[e] = 0.5 if ea is None else cmp(-ea, -eb)
        it["picks"] = p
        s4rows = gem.get(("S4", g, aid)) or []
        known = sum(1 for r in s4rows if r["out"]["known"])
        it["gemini_known"] = (known >= 3) if len(s4rows) == 4 else (bool(s4rows) and known / len(s4rows) >= 0.75)

    cl, shared = clusters([i for i in items if i["covered"]], maps)
    for it in items:
        cl.setdefault(it["artist_id"], it["artist_id"])
        it["cluster"] = cl[it["artist_id"]]
        it["shared_map"] = it["artist_id"] in shared
        it["picks"]["E12"] = 0.5 if it["shared_map"] else it["picks"]["S1"]

    # ---------- populations ----------
    pops, coverage, pool = populations_full(items)
    keyset = lambda pop: {(i["group"], i["artist_id"], i["gold"], i["other"]) for i in pop}
    member = {name: keyset(pop) for name, pop in pops.items()}
    scored = set().union(*member.values()) if member else set()
    missing = [i for i in items if (i["group"], i["artist_id"], i["gold"], i["other"]) in scored and i["covered"] and not i["pair_map"]]
    unbalanced = [i for i in items if i["group"] in WITHIN and (i["group"], i["artist_id"], i["gold"], i["other"]) not in scored]
    for it in items:
        k = (it["group"], it["artist_id"], it["gold"], it["other"])
        it["populations"] = [name for name, s in member.items() if k in s]
    dump(DATA / f"picks_{SNAP}{'_stub' if STUB else ''}.json", items)

    summary = {}
    pobj = {}
    for name, pop in pops.items():
        if not pop:
            summary[name] = {"n_items": 0}
            continue
        P = pobj[name] = Pop(pop, cl)
        summary[name] = {"n_items": len(pop), "n_clusters": P.nc, "n_pairs": P.np_,
                         "macro": P.score(), "plain_macro": P.plain_macro(),
                         "micro": {s: float(P.S[:, P.col[s]].mean()) for s in SYSTEMS},
                         "ties": {s: float(np.mean(P.S[:, P.col[s]] == 0.5)) for s in SYSTEMS},
                         "decisive": {s: (float(P.S[P.S[:, P.col[s]] != 0.5, P.col[s]].mean())
                                          if np.any(P.S[:, P.col[s]] != 0.5) else None) for s in SYSTEMS}}
    if unbalanced:
        summary["unbalanced"] = {"n_items": len(unbalanced),
                                 "micro": {s: statistics.fmean(i["picks"][s] for i in unbalanced) for s in NULLS}}

    stats = {}
    P1 = pobj.get("P1")
    if P1:
        stats["ci_clusters"] = P1.bootstrap([("S1", s) for s in LLM + NULLS] + [("E9", "S4")])
        stats["ci_pairs"] = P1.bootstrap([("S1", s) for s in LLM + NULLS], pairs=True, n=2000)
        stats["p_S1_over"] = {s: P1.sign_flip("S1", s) for s in LLM + NULLS}
        stats["p_E9_over_S4"] = P1.sign_flip("E9", "S4")
        stats["p_llm_over_S1"] = {s: P1.sign_flip(s, "S1") for s in LLM}
        stats["p_llm_over_S1_holm"] = holm(stats["p_llm_over_S1"])

    # ---------- strata (7.3) ----------
    STRAT_SYS = CONFIRM + ["R1", "E9"]

    def strat(pop, pred):
        sub = [i for i in pop if pred(i)]
        if not sub:
            return {"n_items": 0}
        P = Pop(sub, cl)
        sc = P.score()
        return {"n_items": len(sub), "n_clusters": P.nc, **{s: round(sc[s], 4) for s in STRAT_SYS}}

    S = {
        "national": lambda i: i.get("national"), "local": lambda i: not i.get("national"),
        "established": lambda i: i.get("tenure") == "established", "new": lambda i: i.get("tenure") == "new",
        "tenure_unknown": lambda i: i.get("tenure") is None,
        "hometown": lambda i: i.get("hometown") is True, "non_hometown": lambda i: i.get("hometown") is False,
        "hometown_unknown": lambda i: i.get("hometown") is None,
        "high_conf": lambda i: i.get("high_conf"), "shazam_confirmed": lambda i: i.get("shazam_confirmed"),
        "presence": lambda i: i["kind"] == "presence", "rank_gap": lambda i: i["kind"] == "rank_gap",
        "album_drop": lambda i: i.get("album_drop"), "same_language": lambda i: i.get("same_language"),
        "gemini_known": lambda i: i.get("gemini_known"), "shared_map": lambda i: i.get("shared_map"),
        **{f"group_{g}": (lambda g: lambda i: i["group"] == g)(g) for g in WITHIN},
    }
    strata = {k: strat(pops["P1"], f) for k, f in S.items()}
    # Coverage strata live on P2, where uncovered artists stay in (review 24).
    strata["P2_qloo_covered"] = strat(pops["P2"], lambda i: i["covered"])
    strata["P2_gemini_known"] = strat(pops["P2"], lambda i: i.get("gemini_known"))
    strata["P2_known_to_both"] = strat(pops["P2"], lambda i: i.get("gemini_known") and i["covered"])
    gm = [strata[f"group_{g}"] for g in pool if strata[f"group_{g}"]["n_items"]]
    strata["equal_weight_over_groups"] = {s: round(statistics.fmean(x[s] for x in gm), 4) for s in STRAT_SYS} if gm else {}

    # ---------- outcome (9) ----------
    out = {"outcome": "C", "conditions": {}}
    if P1:
        m = summary["P1"]["macro"]
        best = max(LLM, key=lambda s: m[s])
        c1 = all(m["S1"] - m[s] >= 0.05 and stats["p_S1_over"][s] < 0.05 for s in LLM)
        c2 = all(stats["p_S1_over"][s] < 0.05 for s in NULLS)
        c3 = bool(pobj.get("P2")) and all(summary["P2"]["macro"]["S1"] - summary["P2"]["macro"][s] > 0 for s in LLM)
        gating = {k: strata[k] for k in ("national", "established", "non_hometown")}
        c4 = all(v["n_items"] and v["S1"] - v[best] > 0 for v in gating.values())   # an empty stratum fails A4
        qual = [g for g in pool if strata[f"group_{g}"].get("n_clusters", 0) >= 10]
        wins_g = sum(1 for g in qual if strata[f"group_{g}"]["S1"] - strata[f"group_{g}"][best] > 0)
        c5 = bool(qual) and wins_g > len(qual) / 2
        out["conditions"] = {"A1": c1, "A2": c2, "A3": c3, "A4": c4, "A5": c5, "best_llm": best,
                             "A4_not_evaluable": [k for k, v in gating.items() if not v["n_items"]],
                             "qualifying_groups": qual, "groups_won": wins_g}
        gem_win = [s for s in LLM if m[s] - m["S1"] >= 0.05 and stats["p_llm_over_S1_holm"][s] < 0.05]
        out["gemini_wins_via"] = gem_win
        out["outcome"] = "A" if all([c1, c2, c3, c4, c5]) else ("B" if gem_win else "C")

    # ---------- 8.7 extras ----------
    extras = {"coverage": coverage, "pool": pool, "covered_artists": len(covered),
              "pair_maps_missing_in_scored_items": len(missing),
              "eligible_lead_artists": len({i["artist_id"] for i in items if i["group"] in WITHIN}),
              "gemini_failures": dict(failures)}
    if P1:
        pop1 = pops["P1"]
        big = lambda i: POPULATION[i["gold"]] > POPULATION[i["other"]]
        extras["bigger_metro_pick_rate"] = {s: statistics.fmean((i["picks"][s] if big(i) else 1 - i["picks"][s]) for i in pop1)
                                            for s in CONFIRM}
        extras["accuracy_when_gold_bigger"] = {s: statistics.fmean(i["picks"][s] for i in pop1 if big(i)) for s in CONFIRM if any(big(i) for i in pop1)}
        extras["accuracy_when_gold_smaller"] = {s: statistics.fmean(i["picks"][s] for i in pop1 if not big(i)) for s in CONFIRM if any(not big(i) for i in pop1)}
        extras["s1_abstention_by_group"] = {g: statistics.fmean(i["picks"]["S1"] == 0.5 for i in pop1 if i["group"] == g)
                                            for g in pool if any(i["group"] == g for i in pop1)}
        agree = [i for i in pop1 if i["picks"]["E4"] == i["picks"]["S1"]]
        extras["E4_agreement_with_S1"] = len(agree) / len(pop1)
        extras["E4_disagreements"] = [{"artist": i["artist"], "gold": i["gold"], "other": i["other"]}
                                      for i in pop1 if i["picks"]["E4"] != i["picks"]["S1"]][:50]

        def order_of(r, A, Bc):
            return r["out"]["rank"][label(A)] < r["out"]["rank"][label(Bc)]
        same_order = cross = tot = 0
        for i in pop1:
            rows = gem.get(("S4", i["group"], i["artist_id"])) or []
            alpha = [r for r in rows if r["key"][3] == "alpha"]
            rev = [r for r in rows if r["key"][3] == "reverse"]
            if len(alpha) == 2 and len(rev) == 2:
                tot += 1
                same_order += order_of(alpha[0], i["gold"], i["other"]) == order_of(alpha[1], i["gold"], i["other"])
                cross += order_of(alpha[0], i["gold"], i["other"]) == order_of(rev[0], i["gold"], i["other"])
        extras["s4_self_agreement"] = same_order / tot if tot else None
        extras["s4_order_agreement"] = cross / tot if tot else None
        # Label-noise ceiling: does Shazam agree with Apple on the items where both cities have a Shazam chart?
        sz = [i for i in pop1 if i.get("shazam_gold") is not None and i.get("shazam_other") is not None]
        ag = sum(1 for i in sz if i["shazam_gold"] and not i["shazam_other"])
        dis = sum(1 for i in sz if i["shazam_other"] and not i["shazam_gold"])
        extras["apple_shazam"] = {"items_with_both_charts": len(sz), "agree": ag, "disagree": dis,
                                  "agreement": ag / (ag + dis) if ag + dis else None}
    if SNAP == "eval" and (DATA / "items_dev.json").exists():
        dev = {(i["group"], i["artist_id"], i["gold"], i["other"]) for i in load(DATA / "items_dev.json")["items"]}
        extras["share_of_P1_items_in_dev"] = (statistics.fmean(((i["group"], i["artist_id"], i["gold"], i["other"]) in dev)
                                                               for i in pops["P1"]) if pops["P1"] else None)

    result = {"snapshot": items_doc.get("snapshot"), "evaluation_date": items_doc.get("evaluation_date"),
              "summary": summary, "stats": stats, "strata": strata, "outcome": out, "extras": extras}
    if missing and not (STUB or "--allow-missing" in sys.argv):
        dump(DATA / f"results_{SNAP}_incomplete.json", result)
        raise SystemExit(f"{len(missing)} scored items lack a per-pair map: rerun systems.py {SNAP} pairs (2.5)")
    dump(DATA / f"results_{SNAP}{'_stub' if STUB else ''}.json", result)
    print(json.dumps({"outcome": out, "P1": {k: summary.get("P1", {}).get(k) for k in ("n_items", "n_clusters", "n_pairs")},
                      "macro_P1": {s: round(v, 3) for s, v in summary.get("P1", {}).get("macro", {}).items()} if P1 else None,
                      "coverage": {g: round(v, 2) for g, v in coverage.items()}}, indent=1))


if __name__ == "__main__":
    main()
