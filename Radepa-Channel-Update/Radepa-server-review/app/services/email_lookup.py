"""Run both providers under one credit reservation, preserving partial success."""
import asyncio
from dataclasses import dataclass
from app.services.abstract_email import AbstractUnavailable, ReputationSummary
from app.services.leakcheck_public import BreachSummary, LeakCheckUnavailable

@dataclass(frozen=True)
class EmailSummary:
    leakcheck: BreachSummary | None
    abstract: ReputationSummary | None

async def lookup_email(email, leakcheck, abstract=None):
    async def fetch(service):
        if service is None:
            return None
        try:
            return await service.lookup_email(email)
        except (LeakCheckUnavailable, AbstractUnavailable):
            return None
    leak, reputation = await asyncio.gather(fetch(leakcheck), fetch(abstract))
    if leak is None and reputation is None:
        raise LeakCheckUnavailable('all_providers_unavailable')
    return EmailSummary(leak, reputation)
