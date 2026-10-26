"""LeakCheck Public API: breach metadata only; never request or retain raw records."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

URL = "https://leakcheck.io/api/public"


class LeakCheckUnavailable(Exception):
    pass


@dataclass(frozen=True)
class BreachSummary:
    found: int
    fields: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]


class LeakCheckPublic:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(timeout=10, transport=transport)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def lookup_email(self, email: str) -> BreachSummary:
        # Only public breach metadata is requested; raw records are never fetched.
        async with self._lock:
            await asyncio.sleep(max(0.0, 1.05 - (time.monotonic() - self._last)))
            self._last = time.monotonic()
            try:
                response = await self._client.get(URL, params={"check": email},
                                                  headers={"Accept": "application/json"})
                if response.status_code == 429:
                    raise LeakCheckUnavailable("rate_limit")
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get("success") is not True:
                    raise LeakCheckUnavailable("invalid_response")
                found = data.get("found")
                fields = data.get("fields")
                sources = data.get("sources")
                if not isinstance(found, int) or found < 0 or not isinstance(fields, list) or not isinstance(sources, list):
                    raise LeakCheckUnavailable("invalid_response")
                return BreachSummary(
                    found=found,
                    fields=tuple(x[:64] for x in fields if isinstance(x, str))[:30],
                    sources=tuple((x.get("name", "")[:100], (x.get("date") or "")[:20])
                                  for x in sources[:30] if isinstance(x, dict)
                                  and isinstance(x.get("name"), str)
                                  and (x.get("date") is None or isinstance(x.get("date"), str))),
                )
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                # Do not log the URL: it contains the queried email address.
                raise LeakCheckUnavailable(type(exc).__name__) from None

    async def close(self) -> None:
        await self._client.aclose()
