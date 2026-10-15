"""Thin async client for the Qloo hackathon API, with retry and a per-instance concurrency cap."""

import asyncio
import os
import random

import httpx

BASE = os.environ.get("QLOO_BASE", "https://hackathon.api.qloo.com")


class QlooError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Qloo {status}: {message}")
        self.status = status


class Qloo:
    def __init__(self):
        self.key = os.environ.get("QLOO_API_KEY", "")
        self.http = httpx.AsyncClient(base_url=BASE, timeout=httpx.Timeout(45.0, connect=10.0))
        self.sem = asyncio.Semaphore(int(os.environ.get("QLOO_CONCURRENCY", "4")))

    async def get(self, path: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        delay = 1.0
        for attempt in range(5):
            async with self.sem:
                try:
                    r = await self.http.get(path, params=params, headers={"X-Api-Key": self.key})
                except (httpx.TimeoutException, httpx.TransportError):
                    r = None
            if r is not None and r.status_code == 200:
                return r.json()
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                try:
                    body = r.json()
                    msg = str(body.get("errors") or body.get("error") or body)[:300]
                except Exception:
                    msg = r.text[:300]
                raise QlooError(r.status_code, msg)
            await asyncio.sleep(delay + random.random() * 0.5)
            delay *= 2
        raise QlooError(503, "Qloo kept rate limiting or timing out")


qloo = Qloo()


def entities(body: dict) -> list:
    res = (body or {}).get("results")
    if isinstance(res, dict):
        return res.get("entities") or []
    return res or []
