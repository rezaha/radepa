from __future__ import annotations
import asyncio
from typing import List, Dict, Any
from app.db.repos import JobRepo, UserRepo
from app.services.serper_service import SerperService
from app.services.duckduckgo_service import DuckDuckGoService
from app.services.serpapi_service import SerpApiService
from app.services.google_cse_service import GoogleCSEService
from app.config import config
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)


def _merge(*source_lists) -> List[Dict[str, Any]]:
    seen, merged = set(), []
    for source_list in source_lists:
        if not isinstance(source_list, list):
            continue
        for item in source_list:
            norm = item.get("link", "").rstrip("/").lower()
            if norm and norm not in seen:
                seen.add(norm)
                merged.append(item)
    return merged


class JobService:

    def __init__(self, serper: SerperService):
        self._serper = serper
        self._ddg = DuckDuckGoService()

        serpapi_keys = [k for k in [config.serpapi_key, config.serpapi_key_2] if k]
        self._serpapi = SerpApiService(serpapi_keys) if serpapi_keys else None

        self._google = GoogleCSEService(config.google_api_key, config.google_cse_id)

        if self._serpapi:
            logger.info("SerpAPI enabled with %d key(s)", len(serpapi_keys))
        if config.google_api_key:
            logger.info("Google CSE enabled")

    async def run_analysis(self, telegram_user_id: int, target_username: str) -> dict:
        from app.services.credit_service import CreditService
        charge_id = CreditService.reserve(telegram_user_id, "instagram")
        deducted = bool(charge_id)
        if not deducted:
            return {"status": "no_credit", "sources": [], "job_id": None}

        try:
            job = JobRepo.create(telegram_user_id, target_username)
            job_id = job["id"]
            JobRepo.mark_charged(job_id)
            logger.info("Job %d started | user=%d | target='%s'",
                        job_id, telegram_user_id, target_username)

            try:
                tasks = [
                    self._serper.analyze(target_username),
                    self._ddg.analyze(target_username),
                ]
                if self._serpapi:
                    tasks.append(self._serpapi.analyze(target_username))
                if config.google_api_key:
                    tasks.append(self._google.analyze(target_username))

                results = await asyncio.gather(*tasks, return_exceptions=True)
                results = [item if isinstance(item, (list, BaseException))
                           else RuntimeError("Invalid provider result") for item in results]
                if all(isinstance(item, BaseException) for item in results):
                    raise RuntimeError("All search providers unavailable")

                serper_r = results[0] if not isinstance(results[0], BaseException) else []
                ddg_r    = results[1] if not isinstance(results[1], BaseException) else []

                idx = 2
                serpapi_r = []
                google_r  = []

                if self._serpapi:
                    serpapi_r = results[idx] if not isinstance(results[idx], BaseException) else []
                    idx += 1
                if config.google_api_key:
                    google_r = results[idx] if not isinstance(results[idx], BaseException) else []

                if isinstance(results[0], BaseException):
                    logger.error("Serper error: %s", type(results[0]).__name__)
                if isinstance(results[1], BaseException):
                    logger.error("DDG error: %s", type(results[1]).__name__)

                sources = _merge(serper_r, ddg_r, serpapi_r, google_r)

            except Exception as exc:
                logger.error("Job %d failed: %s", job_id, type(exc).__name__)
                JobRepo.fail(job_id)
                return {"status": "failed", "sources": [], "job_id": job_id}

            if sources:
                JobRepo.save_sources(job_id, sources)

            summary = (
                f"{len(sources)} نتیجه "
                f"(serper:{len(serper_r)} "
                f"+ ddg:{len(ddg_r)} "
                f"+ serpapi:{len(serpapi_r)} "
                f"+ google:{len(google_r)})"
            )
            JobRepo.finish(job_id, summary)
            logger.info("Job %d done: %s", job_id, summary)

            CreditService.complete(charge_id)
            return {"status": "ok", "sources": sources, "job_id": job_id}

        except Exception as exc:
            logger.error("Analysis persistence failed: %s", type(exc).__name__)
            if "job_id" in locals():
                JobRepo.fail(job_id)
            return {"status": "failed", "sources": [], "job_id": locals().get("job_id")}
        finally:
            CreditService.refund(charge_id)
