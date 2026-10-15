"""Identity check bookkeeping (5.2) and hometown blanks (4.6).

  python identity.py <snap> prepare          verdicts carried over by (artist ID, Qloo entity ID); the rest go to
                                             spike/out/taste/<snap>/identity_todo.json for the reviewer workflow
  python identity.py <snap> merge <output>   merge the workflow's output with the carried verdicts into
                                             data/identity_<snap>.json and fill hometown blanks in data/items_<snap>.json
"""

import json
import sys

from common import DATA, GROUPS, PRIVATE, dump, fold, load

SNAP, STEP = sys.argv[1], sys.argv[2]
CARRY = PRIVATE / "identity_carry.json"
ALIAS = {"new delhi": "Delhi", "bombay": "Mumbai", "bangalore": "Bengaluru", "new york": "New York City",
         "washington": "Washington D.C.", "washington, d.c.": "Washington D.C.", "johannesburg": "Johannesburg"}


def metro(place: str) -> str:
    f = fold(place).split(",")[0].strip()
    if f in ALIAS:
        return ALIAS[f]
    for c in {c for cs in GROUPS.values() for c in cs}:
        if fold(c) == f:
            return c
    return "elsewhere"


def main():
    inp = load(PRIVATE / SNAP / "identity_input.json")
    res = load(PRIVATE / SNAP / "resolution.json")
    carry = load(CARRY) if CARRY.exists() else {}
    if STEP == "prepare":
        todo = [x for x in inp if not (x["artist_id"] in carry and carry[x["artist_id"]]["entity_id"] == res[x["artist_id"]]["entity_id"])]
        dump(PRIVATE / SNAP / "identity_todo.json", todo)
        print(f"{len(inp)} matches; {len(inp) - len(todo)} carried over; {len(todo)} to review")
        return
    out = load(sys.argv[3])
    out = out.get("result", out)
    verdicts = {}
    for x in inp:
        aid = x["artist_id"]
        if aid in out.get("verdicts", {}):
            verdicts[aid] = out["verdicts"][aid]
            carry[aid] = {"entity_id": res[aid]["entity_id"], "verdict": verdicts[aid]}
        elif aid in carry and carry[aid]["entity_id"] == res[aid]["entity_id"]:
            verdicts[aid] = carry[aid]["verdict"]
        else:
            verdicts[aid] = "fail"   # unchecked at the cutoff counts as fail
    dump(CARRY, carry)
    old = load(DATA / "identity_dev.json") if (DATA / "identity_dev.json").exists() else {}
    hometowns = {**old.get("hometowns", {}), **out.get("hometowns", {})}
    dump(DATA / f"identity_{SNAP}.json", {"snapshot": SNAP, "method": "two independent Claude reviewers per artist, blind "
                                          "to every system output; pass needs both; verdicts carry over when the "
                                          "Qloo entity is unchanged", "verdicts": verdicts, "hometowns": hometowns})
    items = load(DATA / f"items_{SNAP}.json")
    filled = 0
    for it in items["items"]:
        if it.get("home_metro") is None and it["artist_id"] in hometowns:
            it["home_metro"] = metro(hometowns[it["artist_id"]])
            it["hometown"] = it["home_metro"] in (it["gold"], it["other"])
            filled += 1
    dump(DATA / f"items_{SNAP}.json", items)
    print(f"verdicts: {sum(v == 'pass' for v in verdicts.values())} pass of {len(verdicts)}; hometown blanks filled on {filled} items")


if __name__ == "__main__":
    main()
