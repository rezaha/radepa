"""Email input helpers shared by direct breach lookups."""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def normalize_email(raw: str) -> str | None:
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return None
    return email


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"
