"""Explicit live smoke check; prints status only, never keys or response bodies."""
import asyncio
import logging
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.services.abstract_email import URL, parse_summary, AbstractUnavailable

async def main():
    logging.disable(logging.CRITICAL)
    key = os.environ.get('ABSTRACT_API_KEY', '').strip()
    if not key:
        print('ABSTRACT_API_KEY: missing; authenticated check not run')
        return 2
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(URL, params={'email': 'onboarding-check@example.com'},
                headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'})
        print(f'AbstractAPI HTTP status: {response.status_code}')
        if response.status_code != 200:
            return 1
        parse_summary(response.json())
        print('Response schema: supported; live connection verified (synthetic example.com address)')
        return 0
    except (httpx.HTTPError, ValueError, AbstractUnavailable) as exc:
        print(f'Connection/schema check failed: {type(exc).__name__}; details suppressed')
        return 1

if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
