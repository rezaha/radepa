from __future__ import annotations
from datetime import datetime, timezone, timedelta

def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def now_iso() -> str:
    return now_utc().isoformat()

def from_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)

def is_expired(iso_str: str | None) -> bool:
    if not iso_str:
        return True
    return from_iso(iso_str) < now_utc()

def days_remaining(iso_str: str | None) -> int:
    if not iso_str:
        return 0
    return max(0, (from_iso(iso_str) - now_utc()).days)

def format_shamsi_approx(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    return from_iso(iso_str).strftime("%Y-%m-%d %H:%M UTC")
