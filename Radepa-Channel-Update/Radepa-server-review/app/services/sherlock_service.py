"""Bounded, optional Sherlock CLI jobs; no shell, API key or paid credit use."""
from __future__ import annotations

import asyncio
from collections import Counter
import csv
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile
import time
from urllib.parse import urlsplit

_USERNAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', re.ASCII)
_CHILD_SECRETS = {
    'BOT_TOKEN', 'ADMIN_IDS', 'PAYMENT_CARD_NUMBER', 'PAYMENT_CARD_HOLDER',
    'SERPER_API_KEY', 'SERPAPI_KEY', 'SERPAPI_KEY_2', 'GOOGLE_API_KEY',
    'GOOGLE_CSE_ID', 'ABSTRACT_API_KEY', 'DB_PATH', 'LOG_FILE', 'TELEGRAM_PROXY_URL',
}


def normalize_username(raw: str) -> str:
    value = raw.strip()
    if value.startswith('@'):
        value = value[1:]
    if not _USERNAME.fullmatch(value):
        raise ValueError('Invalid Sherlock username')
    return value


@dataclass(frozen=True)
class SiteResult:
    name: str
    url: str
    status: str
    http_status: str = ''


def _valid_link(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return (len(value) <= 1024 and not any(c.isspace() or ord(c) < 32 for c in value)
                and parts.scheme in ('http', 'https') and bool(parts.hostname)
                and parts.username is None and parts.password is None)
    except ValueError:
        return False


@dataclass(frozen=True)
class SherlockResult:
    status: str  # complete, partial, timeout, unavailable, failed
    records: tuple[SiteResult, ...] = ()
    reason: str = ''
    returncode: int | None = None

    @property
    def found(self) -> tuple[SiteResult, ...]:
        seen = set()
        result = []
        for row in self.records:
            failed_http = row.http_status in ('403', '429') or (row.http_status.isdigit() and int(row.http_status) >= 500)
            if row.status == 'Claimed' and not failed_http and row.name and _valid_link(row.url) and row.url not in seen:
                seen.add(row.url)
                result.append(row)
        return tuple(result)

    @property
    def status_counts(self) -> dict[str, int]:
        return dict(Counter(row.status for row in self.records))


def read_csv(path: Path, returncode: int) -> SherlockResult:
    records = []
    issue = ''
    if not path.is_file() or path.is_symlink():
        return SherlockResult('failed', reason='missing_csv', returncode=returncode)
    if path.stat().st_size > 8 * 1024 * 1024:
        return SherlockResult('failed', reason='output_limit', returncode=returncode)
    try:
        with path.open(newline='', encoding='utf-8-sig') as stream:
            rows = csv.DictReader(stream, strict=True)
            if not {'name', 'url_user', 'exists'} <= set(rows.fieldnames or ()):
                return SherlockResult('failed', reason='invalid_csv', returncode=returncode)
            for row in rows:
                if len(records) >= 5000:
                    issue = 'output_limit'
                    break
                if None in row or any(row.get(key) is None for key in ('name', 'url_user', 'exists')):
                    issue = 'invalid_csv'
                    continue
                status = row['exists'].strip()
                name = ' '.join(row['name'].split())[:80]
                url = row['url_user'].strip()
                http = (row.get('http_status') or '').strip()
                records.append(SiteResult(name, url, status, http))
                if (status not in ('Claimed', 'Available') or http in ('403', '429')
                        or (http.isdigit() and int(http) >= 500)
                        or (status == 'Claimed' and (not name or not _valid_link(url)))):
                    issue = issue or 'incomplete_sites'
    except (OSError, UnicodeError, csv.Error):
        issue = 'invalid_csv'
    if not records:
        return SherlockResult('failed', reason=issue or 'empty_csv', returncode=returncode)
    if returncode != 0:
        issue = 'nonzero_exit'
    return SherlockResult('partial' if issue else 'complete', tuple(records), issue, returncode)


@dataclass(frozen=True)
class Permit:
    user_id: int
    username: str


class AdmissionRejected(Exception):
    def __init__(self, reason: str, retry_after: int = 0):
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


class SherlockService:
    def __init__(self, *, enabled=False, binary='sherlock', max_concurrent=1,
                 site_timeout=10, total_timeout=120, cooldown=60):
        if not (1 <= max_concurrent <= 4 and 1 <= site_timeout <= 30
                and site_timeout <= total_timeout <= 300 and 1 <= cooldown <= 3600):
            raise ValueError('Invalid Sherlock resource limits')
        self.enabled, self.binary = enabled, binary
        self.max_concurrent, self.site_timeout = max_concurrent, site_timeout
        self.total_timeout, self.cooldown = total_timeout, cooldown
        self._active: dict[int, Permit] = {}
        self._next: dict[int, float] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def reserve(self, user_id: int, username: str) -> Permit:
        username = normalize_username(username)
        if not self.enabled or self._closed:
            raise AdmissionRejected('disabled')
        now = time.monotonic()
        for key, deadline in list(self._next.items()):
            if deadline <= now and key not in self._active:
                del self._next[key]
        if user_id in self._active:
            raise AdmissionRejected('busy')
        if self._next.get(user_id, 0) > now:
            raise AdmissionRejected('rate_limited', math.ceil(self._next[user_id] - now))
        if len(self._active) >= self.max_concurrent:
            raise AdmissionRejected('full')
        permit = Permit(user_id, username)
        self._active[user_id] = permit
        self._next[user_id] = now + self.cooldown
        return permit

    def finish(self, permit: Permit) -> None:
        if self._active.get(permit.user_id) is permit:
            del self._active[permit.user_id]

    def track(self, task: asyncio.Task, permit: Permit) -> None:
        self._tasks.add(task)
        def done(finished):
            self._tasks.discard(finished)
            self.finish(permit)
        task.add_done_callback(done)

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()

    async def _stop(self, process) -> None:
        if process.returncode is not None:
            return
        def send(sig):
            try:
                if os.name == 'posix':
                    os.killpg(process.pid, sig)
                elif sig == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()
            except ProcessLookupError:
                pass
        send(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            send(signal.SIGKILL)
            await process.wait()

    async def execute(self, permit: Permit) -> SherlockResult:
        """Run a reserved job. Its owner keeps the permit until delivery finishes."""
        if self._active.get(permit.user_id) is not permit:
            raise ValueError('Inactive Sherlock permit')
        binary = shutil.which(self.binary)
        if not binary:
            return SherlockResult('unavailable', reason='binary_missing')
        child_env = {key: value for key, value in os.environ.items() if key not in _CHILD_SECRETS}
        with tempfile.TemporaryDirectory(prefix='radepa-sherlock-') as folder:
            output = Path(folder) / (permit.username + '.csv')
            process = None
            timed_out = False
            try:
                async def run():
                    nonlocal process
                    process = await asyncio.create_subprocess_exec(
                        binary, permit.username, '--csv', '--print-all', '--local',
                        '--timeout', str(self.site_timeout), '--folderoutput', folder,
                        cwd=folder, env=child_env,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        start_new_session=(os.name == 'posix'),
                    )
                    return await process.wait()
                await asyncio.wait_for(run(), timeout=self.total_timeout)
            except asyncio.TimeoutError:
                timed_out = True
                if process:
                    await self._stop(process)
            except asyncio.CancelledError:
                if process:
                    await self._stop(process)
                raise
            except OSError:
                if process:
                    await self._stop(process)
                return SherlockResult('unavailable', reason='execution_error')
            result = read_csv(output, process.returncode if process else -1)
            if timed_out:
                return SherlockResult('timeout', result.records, 'total_timeout', result.returncode)
            return result
