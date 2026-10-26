# === app/services/email_verification.py ===
"""
تایید مالکیت ایمیل (Email Ownership Verification)

جریان کار:
  1. کاربر ایمیلش را در تلگرام می‌فرستد.
  2. یک توکن تصادفی ساخته می‌شود؛ فقط «هش» آن در SQLite ذخیره می‌شود.
  3. لینک تایید به همان ایمیل ارسال می‌شود (SMTP).
  4. کاربر روی لینک کلیک می‌کند و دکمه‌ی تایید را می‌زند.
  5. فقط بعد از این، is_email_verified(...) مقدار True می‌دهد.

نکته‌ها:
  - هیچ فلگ MOCK/bypass در این فایل وجود ندارد.
  - توکن هرگز لاگ نمی‌شود.
  - محدودیت روزانه هم برای هر کاربر تلگرام و هم برای هر ایمیل (جلوگیری از mail-bombing).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Optional, Tuple

from app.config import config
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


# ── دیتابیس ──────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.db_path, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_tables() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS email_verifications (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                email            TEXT    NOT NULL,
                token_hash       TEXT    NOT NULL UNIQUE,
                created_at       INTEGER NOT NULL,
                expires_at       INTEGER NOT NULL,
                used_at          INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_ev_user  ON email_verifications(telegram_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_ev_email ON email_verifications(email, created_at);

            CREATE TABLE IF NOT EXISTS verified_emails (
                telegram_user_id INTEGER NOT NULL,
                email            TEXT    NOT NULL,
                verified_at      INTEGER NOT NULL,
                PRIMARY KEY (telegram_user_id, email)
            );
            """
        )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(raw: str) -> Optional[str]:
    email = (raw or "").strip().lower()
    if len(email) > 254 or " " in email or not _EMAIL_RE.match(email):
        return None
    return email


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


# ── ارسال ایمیل ──────────────────────────────────────────────

def _send_mail_sync(to_email: str, link: str, ttl_minutes: int) -> None:
    host = _env("SMTP_HOST")
    port = _env_int("SMTP_PORT", 587)
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    sender = _env("SMTP_FROM") or user
    if not (host and user and password and sender):
        raise RuntimeError("SMTP settings are incomplete in .env")

    msg = EmailMessage()
    msg["Subject"] = "تایید ایمیل | ردپاگرد"
    msg["From"] = sender
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(
        f"سلام،\n\n"
        f"درخواستی برای تایید این ایمیل در ربات ردپاگرد ثبت شد.\n"
        f"اگر خودت این درخواست را دادی، لینک زیر را باز کن و دکمه‌ی تایید را بزن "
        f"(اعتبار لینک: {ttl_minutes} دقیقه):\n\n{link}\n\n"
        f"اگر این درخواست از طرف تو نبوده، این ایمیل را نادیده بگیر. "
        f"در این صورت هیچ اتفاقی نمی‌افتد و هیچ جستجویی انجام نمی‌شود.\n"
    )

    ctx = ssl.create_default_context()
    use_ssl = port == 465 or _env("SMTP_USE_SSL").lower() in ("1", "true", "yes")
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)


# ── درخواست تایید ────────────────────────────────────────────

def _create_token_sync(telegram_user_id: int, email: str) -> Tuple[str, str]:
    """returns (status, token). status: ok | user_limit | email_limit"""
    now = int(time.time())
    day_ago = now - 86400
    ttl = _env_int("VERIFY_TTL_MINUTES", 10) * 60
    max_user = _env_int("VERIFY_MAX_PER_USER_DAY", 3)
    max_email = _env_int("VERIFY_MAX_PER_EMAIL_DAY", 2)

    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            n_user = c.execute(
                "SELECT COUNT(*) FROM email_verifications WHERE telegram_user_id=? AND created_at>?",
                (telegram_user_id, day_ago),
            ).fetchone()[0]
            if n_user >= max_user:
                c.execute("ROLLBACK")
                return "user_limit", ""
            n_email = c.execute(
                "SELECT COUNT(*) FROM email_verifications WHERE email=? AND created_at>?",
                (email, day_ago),
            ).fetchone()[0]
            if n_email >= max_email:
                c.execute("ROLLBACK")
                return "email_limit", ""

            # توکن‌های قبلیِ هنوز-معتبر برای همین کاربر/ایمیل باطل می‌شوند
            c.execute(
                "UPDATE email_verifications SET used_at=? "
                "WHERE telegram_user_id=? AND email=? AND used_at IS NULL",
                (now, telegram_user_id, email),
            )
            token = secrets.token_urlsafe(32)
            c.execute(
                "INSERT INTO email_verifications "
                "(telegram_user_id, email, token_hash, created_at, expires_at) VALUES (?,?,?,?,?)",
                (telegram_user_id, email, _hash(token), now, now + ttl),
            )
            c.execute("COMMIT")
            return "ok", token
        except Exception:
            c.execute("ROLLBACK")
            raise


def _drop_token_sync(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM email_verifications WHERE token_hash=?", (_hash(token),))


async def request_verification(telegram_user_id: int, raw_email: str) -> Tuple[str, Optional[str]]:
    """
    returns (code, normalized_email)
    code: invalid | user_limit | email_limit | smtp_error | sent
    """
    email = normalize_email(raw_email)
    if not email:
        return "invalid", None

    status, token = await asyncio.to_thread(_create_token_sync, telegram_user_id, email)
    if status != "ok":
        return status, email

    base = _env("VERIFY_BASE_URL").rstrip("/")
    if not base:
        await asyncio.to_thread(_drop_token_sync, token)
        logger.error("VERIFY_BASE_URL is not set")
        return "smtp_error", email

    link = f"{base}/verify?t={token}"
    ttl_min = _env_int("VERIFY_TTL_MINUTES", 10)
    try:
        await asyncio.to_thread(_send_mail_sync, email, link, ttl_min)
    except Exception as e:  # نه توکن، نه لینک لاگ نمی‌شود
        logger.error("Verification email failed (%s): %s", type(e).__name__, e)
        await asyncio.to_thread(_drop_token_sync, token)
        return "smtp_error", email

    logger.info("Verification email sent to %s for tg=%s", mask_email(email), telegram_user_id)
    return "sent", email


# ── تایید توکن ───────────────────────────────────────────────

def peek_token_sync(token: str) -> bool:
    """بدون مصرف کردن توکن، فقط می‌گوید هنوز معتبر است یا نه."""
    if not token or len(token) > 100:
        return False
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM email_verifications WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
            (_hash(token), int(time.time())),
        ).fetchone()
    return row is not None


def confirm_token_sync(token: str) -> Optional[Tuple[int, str]]:
    """توکن را یک‌بار مصرف می‌کند. returns (telegram_user_id, email) یا None."""
    if not token or len(token) > 100:
        return None
    now = int(time.time())
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            row = c.execute(
                "SELECT id, telegram_user_id, email FROM email_verifications "
                "WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                (_hash(token), now),
            ).fetchone()
            if not row:
                c.execute("ROLLBACK")
                return None
            c.execute("UPDATE email_verifications SET used_at=? WHERE id=?", (now, row["id"]))
            c.execute(
                "INSERT INTO verified_emails (telegram_user_id, email, verified_at) VALUES (?,?,?) "
                "ON CONFLICT(telegram_user_id, email) DO UPDATE SET verified_at=excluded.verified_at",
                (row["telegram_user_id"], row["email"], now),
            )
            c.execute("COMMIT")
            return int(row["telegram_user_id"]), row["email"]
        except Exception:
            c.execute("ROLLBACK")
            raise


def _is_verified_sync(telegram_user_id: int, email: str, max_age_hours: int) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT verified_at FROM verified_emails WHERE telegram_user_id=? AND email=?",
            (telegram_user_id, email),
        ).fetchone()
    return bool(row) and (int(time.time()) - int(row["verified_at"])) <= max_age_hours * 3600


async def is_email_verified(telegram_user_id: int, raw_email: str, max_age_hours: int = 24) -> bool:
    """هر قابلیتی که به ایمیل کاربر نیاز دارد (مثل چک نشتی) باید اول این را چک کند."""
    email = normalize_email(raw_email)
    if not email:
        return False
    return await asyncio.to_thread(_is_verified_sync, telegram_user_id, email, max_age_hours)
