"""Two-tier cache: process memory, then Firestore (named DB) or a local folder in dev.

Only small JSON values go in here: search hits and per-city aggregates. Raw heatmaps stay out.
Text people paste stays in process memory (keep=False); the shared tiers hold Qloo lookups and the samples.
"""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

TTL = 14 * 86400


class Cache:
    def __init__(self):
        self.mem: dict[str, tuple[float, object]] = {}
        self.db = None
        self.disk = None
        name = os.environ.get("ROOM_FIRESTORE_DB")
        if name:
            try:
                from google.cloud import firestore
                self.db = firestore.Client(database=name)
            except Exception as e:  # cache is an accelerator; the app runs without it
                print(f"cache: firestore unavailable ({e})")
        folder = os.environ.get("ROOM_DISK_CACHE")
        if folder:
            self.disk = Path(folder)
            self.disk.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(*parts) -> str:
        return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    async def get(self, k: str):
        hit = self.mem.get(k)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
        if self.disk:
            f = self.disk / f"{k}.json"
            if f.exists():
                v = json.loads(f.read_text(encoding="utf-8"))
                self.mem[k] = (time.time(), v)
                return v
        if self.db:
            try:
                snap = await asyncio.to_thread(self.db.collection("cache").document(k).get)
                if snap.exists:
                    d = snap.to_dict()
                    if time.time() - d.get("t", 0) < TTL:
                        v = json.loads(d["v"])
                        self.mem[k] = (time.time(), v)
                        return v
            except Exception as e:
                print(f"cache: read failed ({e})")
        return None

    async def set(self, k: str, v, keep: bool = True):
        self.mem[k] = (time.time(), v)
        if len(self.mem) > 5000:
            for old in sorted(self.mem, key=lambda x: self.mem[x][0])[:1000]:
                self.mem.pop(old, None)
        if not keep:
            return
        if self.disk:
            (self.disk / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
        if self.db:
            try:
                await asyncio.to_thread(
                    self.db.collection("cache").document(k).set, {"t": time.time(), "v": json.dumps(v)}
                )
            except Exception as e:
                print(f"cache: write failed ({e})")


cache = Cache()


async def cached(k: str, fn):
    """Return the cached value for k, or compute it with the coroutine fn and store it."""
    v = await cache.get(k)
    if v is not None:
        return v
    v = await fn()
    if v is not None:
        await cache.set(k, v)
    return v
