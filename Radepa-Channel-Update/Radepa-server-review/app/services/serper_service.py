import asyncio
import time
import httpx
from typing import Any, Dict, List
from app.config import config
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

QUERY_TEMPLATES = [
    'site:instagram.com "{username}"',
    'site:instagram.com "{username}" comment',
    'site:instagram.com/p/ "{username}"',
    'site:instagram.com/reel/ "{username}"',
    '"{username}" instagram',
    'instagram "{username}"',
]
SERPER_URL = "https://google.serper.dev/search"


class SerperService:

    def __init__(self):
        self._api_key = config.serper_api_key
        self._country = config.serper_country
        self._language = config.serper_language
        self._top_n = 10
        self._client = httpx.AsyncClient(timeout=20.0)
        self._last: float = 0.0

    async def _rl(self) -> None:
        e = time.monotonic() - self._last
        if e < 0.3:
            await asyncio.sleep(0.3 - e)
        self._last = time.monotonic()

    async def _search_one(self, query: str, retries: int = 3) -> List[Dict[str, Any]]:
        await self._rl()
        for i in range(1, retries + 1):
            try:
                r = await self._client.post(
                    SERPER_URL,
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "q": query,
                        "gl": self._country,
                        "hl": self._language,
                        "num": self._top_n,
                    },
                )
                r.raise_for_status()
                res = r.json().get("organic", [])
                logger.info("Serper '%s' -> %d", query[:50], len(res))
                return res
            except Exception as e:
                logger.warning("Serper attempt %d: %s", i, e)
                if i < retries:
                    await asyncio.sleep(2 ** i)
        raise RuntimeError("Serper requests failed")

    async def analyze(self, username: str) -> List[Dict[str, Any]]:
        tasks = [
            self._search_one(t.replace("{username}", username))
            for t in QUERY_TEMPLATES
        ]
        groups = await asyncio.gather(*tasks, return_exceptions=True)
        if all(isinstance(group, Exception) for group in groups):
            raise RuntimeError("All Serper searches failed")
        seen: set = set()
        merged: List[Dict[str, Any]] = []
        for idx, group in enumerate(groups):
            if isinstance(group, Exception):
                continue
            for rank, item in enumerate(group, 1):
                link = item.get("link", "")
                norm = link.rstrip("/").lower()
                if norm in seen:
                    continue
                seen.add(norm)
                merged.append({
                    "title": item.get("title", "") or "",
                    "link": link,
                    "snippet": item.get("snippet", "") or "",
                    "rank": rank,
                    "query_pattern": QUERY_TEMPLATES[idx],
                    "source": "serper",
                    "username": username,
                })
        logger.info("Serper analyze('%s') -> %d", username, len(merged))
        return merged

    async def close(self) -> None:
        await self._client.aclose()
