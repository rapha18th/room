import json, os, sys, time, requests
from pathlib import Path
KEY=[l.split("=",1)[1].strip() for l in (Path(__file__).parent.parent/".env").read_text().splitlines() if l.startswith("QLOO_API_KEY=")][0]
B="https://hackathon.api.qloo.com"
def g(path, **p):
    t=time.time(); r=requests.get(B+path, params=p, headers={"X-Api-Key":KEY}, timeout=60)
    try: d=r.json()
    except Exception: d={"text":r.text[:300]}
    return r.status_code, int((time.time()-t)*1000), d
def heat(d):
    return ((d.get("results") or {}).get("heatmap") or [])
