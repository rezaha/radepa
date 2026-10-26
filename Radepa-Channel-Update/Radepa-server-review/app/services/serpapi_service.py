import asyncio
import httpx
from typing import Any, Dict, List
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

QUERY_TEMPLATES = [
    'site:instagram.com "{username}"',
    'site:instagram.com "{username}" comment',
    '"{username}" instagram -site:instagram.com',
    '"{username}" instagram mention',
    '"{username}" instagram tagged',
    'instagram "{username}"',
]

SERPAPI_URL = "https://serpapi.com/search"


class SerpApiService:

    def __init__(self, api_keys: List[str]):
        self._api_keys = [k for k in api_keys if k]
        self._current = 0
        self._client = httpx.AsyncClient(timeout=20.0)

    def _get_key(self) -> str:
        return self._api_keys[self._current % len(self._api_keys)]

    def _rotate(self) -> None:
        self._current += 1

    async def _search_one(self, query: str) -> List[Dict[str, Any]]:
        if not self._api_keys:
            return []
        for attempt in range(len(self._api_keys) * 2):
            try:
                r = await self._client.get(
                    SERPAPI_URL,
                    params={
                        "q": query,
                        "api_key": self._get_key(),
                        "engine": "google",
                        "gl": "ir",
                        "hl": "fa",
                        "num": 10,
                    },
                )
                if r.status_code in (403, 429):
                    self._rotate()
                    continue
                r.raise_for_status()
                res = r.json().get("organic_results", [])
                logger.info("SerpAPI '%s' -> %d", query[:50], len(res))
                return res
            except Exception as e:
                logger.warning("SerpAPI error: %s", e)
                self._rotate()
                await asyncio.sleep(1)
        raise RuntimeError("SerpAPI requests failed")

    async def analyze(self, username: str) -> List[Dict[str, Any]]:
        if not self._api_keys:
            return []
        tasks = [
            self._search_one(t.replace("{username}", username))
            for t in QUERY_TEMPLATES
        ]
        groups = await asyncio.gather(*tasks, return_exceptions=True)
        if all(isinstance(group, Exception) for group in groups):
            raise RuntimeError("All SerpAPI searches failed")
        seen: set = set()
        merged: List[Dict[str, Any]] = []
        for idx, group in enumerate(groups):
            if isinstance(group, Exception):
                continue
            for rank, item in enumerate(group, 1):
                link = item.get("link", "")
                norm = link.rstrip("/").lower()
                if not norm or norm in seen:
                    continue
                tc = (
                    (item.get("title", "") or "") + " " +
                    (item.get("snippet", "") or "") + " " +
                    link
                ).lower()
                if username.lower() not in tc:
                    continue
                seen.add(norm)
                merged.append({
                    "title": item.get("title", "") or "",
                    "link": link,
                    "snippet": item.get("snippet", "") or "",
                    "rank": rank,
                    "query_pattern": QUERY_TEMPLATES[idx],
                    "source": "serpapi",
                    "username": username,
                })
        logger.info("SerpAPI analyze('%s') -> %d", username, len(merged))
        return merged

    async def close(self) -> None:
        await self._client.aclose()
