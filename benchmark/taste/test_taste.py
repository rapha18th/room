"""Unit tests for the Taste track. Run: python benchmark/taste/test_taste.py (no API calls)."""

import sys

sys.argv = [sys.argv[0], "dev", "--stub"]

import common  # noqa: E402
import engine  # noqa: E402
import score  # noqa: E402
import systems  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1


# engine.aggregate: the product's Loved, cells, p75, rank and popularity per city.
room = [{"name": "Atlanta", "lat": 33.75, "lon": -84.39, "hh": 0.2, "hw": 0.22},
        {"name": "Dallas", "lat": 32.78, "lon": -96.80, "hh": 0.22, "hw": 0.25}]
cells = [{"location": {"latitude": 33.7, "longitude": -84.4}, "query": {"affinity": a, "affinity_rank": a / 2, "popularity": 0.9}}
         for a in (0.2, 0.4, 0.6, 0.8, 1.0)] + \
        [{"location": {"latitude": 32.8, "longitude": -96.8}, "query": {"affinity": 0.3}},
         {"location": {"latitude": 10.0, "longitude": 10.0}, "query": {"affinity": 0.99}}]
agg = engine.aggregate(cells, room)
check(agg["cities"]["Atlanta"]["cells"] == 5 and agg["cities"]["Atlanta"]["median"] == 0.6, "Atlanta median")
check(agg["cities"]["Dallas"]["cells"] == 1 and agg["total"] == 7, "Dallas cells, total includes outside cells")

# S1: the 5-cell gate, then Loved, then the ratio.
base = {"cities": {"Atlanta": {"cells": 10}, "Dallas": {"cells": 2}}}
ka, kd = score.s1_key(agg, base, "Atlanta"), score.s1_key(agg, base, "Dallas")
check(ka[0] and not kd[0] and score.cmp(ka, kd) == 1.0, "a gated city loses to a scored one")
check(score.cmp((False, 0.0, 0.5), (False, 0.0, 0.5)) == 0.5, "full tie is half credit")
check(score.cmp((False, 0.0, 0.6), (False, 0.0, 0.5)) == 1.0, "ratio breaks a tie of undefined Loved")

# 4.5 balancing.
items = [{"group": "us", "artist_id": f"a{i}", "gold": "Atlanta", "other": "Dallas"} for i in range(5)] + \
        [{"group": "us", "artist_id": f"d{i}", "gold": "Dallas", "other": "Atlanta"} for i in range(2)] + \
        [{"group": "us", "artist_id": "x", "gold": "Miami", "other": "Dallas"}]
bal = score.balance(items)
check(sum(1 for i in bal if i["gold"] == "Atlanta") == 2 and sum(1 for i in bal if i["gold"] == "Dallas") == 2, "2 each way")
check(not any(i["gold"] == "Miami" for i in bal), "one-direction pair contributes nothing")

# Pair-balanced cluster macro (12.19): a fixed per-pair predictor scores exactly 50%, with uneven cluster sizes.
def mk(aid, gold, other, picks):
    return {"group": "us", "artist_id": aid, "gold": gold, "other": other, "picks": picks}
pop = [mk("big", "Atlanta", "Dallas", {}), mk("big", "Atlanta", "Miami", {}), mk("big", "Atlanta", "Houston", {}),
       mk("s1", "Dallas", "Atlanta", {}), mk("s2", "Miami", "Atlanta", {}), mk("s3", "Houston", "Atlanta", {}),
       mk("big", "Dallas", "Miami", {}), mk("s4", "Miami", "Dallas", {})]
for it in pop:   # always pick the alphabetically first city of the pair: fixed per pair
    pick = 1.0 if it["gold"] == min(it["gold"], it["other"]) else 0.0
    it["picks"] = {"S1": pick, "S4": 0.5}
cl = {i["artist_id"]: i["artist_id"] for i in pop}
P = score.Pop(pop, cl, systems=["S1", "S4"])
check(abs(P.score()["S1"] - 0.5) < 1e-12, "fixed per-pair predictor scores 50% under the primary metric")
check(abs(P.plain_macro()["S1"] - 0.5) > 0.01, "the plain cluster macro drifts off 50% here (why 12.19 exists)")
check(P.sign_flip("S4", "S4") == 1.0, "identical systems: p = 1")
for it in pop:
    it["picks"]["S4"] = 1.0
P = score.Pop(pop, cl, systems=["S1", "S4"])
check(abs(P.sign_flip("S4", "S1") - 1 / 2 ** P.nc) < 1e-9 or P.sign_flip("S4", "S1") < 0.2, "a perfect system beats a coin flip")
h = score.holm({"a": 0.01, "b": 0.04, "c": 0.03})
check(abs(h["a"] - 0.03) < 1e-9 and abs(h["c"] - 0.06) < 1e-9 and abs(h["b"] - 0.06) < 1e-9, "Holm step-down")
check(score.avg_ranks({"a": 3, "b": 1, "c": 1}) == {"a": 1, "b": 2.5, "c": 2.5}, "tied keys share the mean rank")

# Spearman with ties.
check(abs(score.spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-9, "spearman monotone")

# Giveaway rule: whole words, accents folded.
check(common.giveaway("LOS DOS DE TAMAULIPAS") == "Tamaulipas", "Mexican state")
check(common.giveaway("Dalvin La Melodia") is None, "Spanish article stays")
check(common.giveaway("Brooks & Dunn") is None, "plain name")

# Gemini answer mapping: exact label or exact city.
labels = ["Atlanta, United States", "Dallas, United States"]
check(systems.match_city("Atlanta", labels) == labels[0] and systems.match_city("atlanta, united states", labels) == labels[0], "labels")
check(systems.match_city("Atlanta, GA", labels) is None, "near-miss labels count as missing")
r = systems.Ranking(known=True, genre="rap", ranking=[systems.Rank(city="Dallas, United States", rank=2),
                                                       systems.Rank(city="Atlanta", rank=1)])
check(systems.parse_rank(r, labels)["rank"] == {labels[0]: 1, labels[1]: 2}, "rank parse")
r2 = systems.Ranking(known=True, genre="rap", ranking=[systems.Rank(city="Atlanta", rank=1)])
check(systems.parse_rank(r2, labels) is None, "a missing city is a transport failure")

print(f"taste tests: {ok} passed")
