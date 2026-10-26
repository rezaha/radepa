# === app/services/duckduckgo_service.py ===
from __future__ import annotations
import asyncio
from typing import Any, Dict, List
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

QUERY_TEMPLATES = [
    'site:instagram.com "{username}"',
    'site:instagram.com "{username}" comment',
    'instagram "{username}" -site:instagram.com',
    '"{username}" instagram mention',
    '"{username}" instagram tagged',
    '"{username}" instagram story',
    '"{username}" اینستاگرام',
    'instagram.com "{username}"',
]


class DuckDuckGoService:

    def _search_sync(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        try:
            from ddgs import DDGS
            results = list(DDGS().text(query, max_results=max_results))
            logger.info("DDG query='%s' → %d results", query[:60], len(results))
            return results
        except Exception as exc:
            logger.warning("DDG error query='%s': %s", query[:50], exc)
            raise RuntimeError("DDG search failed") from None

    async def analyze(self, username: str) -> List[Dict[str, Any]]:
        queries = [t.replace("{username}", username) for t in QUERY_TEMPLATES]
        loop = asyncio.get_event_loop()
        tasks = [loop.run_in_executor(None, self._search_sync, q) for q in queries]
        groups = await asyncio.gather(*tasks, return_exceptions=True)
        if all(isinstance(group, Exception) for group in groups):
            raise RuntimeError("All DDG searches failed")

        seen, merged = set(), []
        for idx, group in enumerate(groups):
            if isinstance(group, Exception):
                logger.error("DDG group[%d] exception: %s", idx, group)
                continue
            for rank, item in enumerate(group, 1):
                link = item.get("href", "") or item.get("url", "")
                norm = link.rstrip("/").lower()
                if not norm or norm in seen:
                    continue

                # فقط نتایج مرتبط با username
                text_to_check = (
                        (item.get("title", "") or "") + " " +
                        (item.get("body", "") or "") + " " +
                        link
                ).lower()
                if username.lower() not in text_to_check:
                    continue

                seen.add(norm)
                merged.append({
                    "title": item.get("title", "") or "",
                    "link": link,
                    "snippet": item.get("body", "") or "",
                    "rank": rank,
                    "query_pattern": QUERY_TEMPLATES[idx],
                    "source": "duckduckgo",
                    "username": username,
                })

        logger.info("DDG analyze('%s') → %d unique", username, len(merged))
        return merged
