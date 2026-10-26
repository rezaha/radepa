# === app/web/verify_server.py ===
"""
وب‌سرور کوچک aiohttp برای لینک تایید ایمیل.

  GET  /verify?t=...  → صفحه‌ی تایید با یک دکمه (توکن مصرف نمی‌شود)
  POST /verify        → تایید نهایی (توکن مصرف می‌شود)
  GET  /healthz

چرا GET توکن را مصرف نمی‌کند؟ اسکنرهای ایمیل و پیش‌نمایش‌ساز لینک‌ها
معمولاً لینک را GET می‌کنند؛ اگر GET تایید می‌کرد، تایید خودکار و بی‌اثبات می‌شد.
"""
from __future__ import annotations

import asyncio
import html
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from aiohttp import web

from app.services import email_verification as ev
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_LIMIT, _WINDOW = 30, 60.0  # ۳۰ درخواست در دقیقه برای هر IP


def _client_ip(request: web.Request) -> str:
    # پشت reverse proxy (nginx/caddy) هدر X-Forwarded-For را می‌گذارد
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[0].strip() if xff else request.remote) or "?"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= _LIMIT:
        return True
    q.append(now)
    return False


def _page(title: str, body: str, status: int = 200) -> web.Response:
    doc = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{html.escape(title)}</title>
<style>body{{font-family:Tahoma,system-ui,sans-serif;background:#0f1117;color:#e2e8f0;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
.c{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:14px;padding:28px;max-width:420px;
width:calc(100% - 32px);text-align:center;line-height:1.9}}
button{{background:#6366f1;color:#fff;border:0;border-radius:10px;padding:12px 28px;font-size:1rem;cursor:pointer}}
p{{color:#94a3b8}}</style></head><body><div class="c">{body}</div></body></html>"""
    return web.Response(text=doc, status=status, content_type="text/html",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


async def verify_get(request: web.Request) -> web.Response:
    if _rate_limited(_client_ip(request)):
        return _page("کندتر", "<h3>تعداد درخواست‌ها زیاد است</h3><p>کمی بعد دوباره تلاش کن.</p>", 429)
    token = request.query.get("t", "")
    if not await asyncio.to_thread(ev.peek_token_sync, token):
        return _page("لینک نامعتبر", "<h3>❌ لینک نامعتبر یا منقضی شده</h3>"
                     "<p>از داخل ربات دوباره درخواست تایید بده.</p>", 400)
    return _page(
        "تایید ایمیل",
        "<h3>تایید ایمیل ردپاگرد</h3><p>اگر خودت این درخواست را داده‌ای، دکمه‌ی زیر را بزن.</p>"
        f'<form method="post" action="/verify"><input type="hidden" name="t" value="{html.escape(token)}">'
        "<button type='submit'>تایید می‌کنم</button></form>",
    )


async def verify_post(request: web.Request) -> web.Response:
    if _rate_limited(_client_ip(request)):
        return _page("کندتر", "<h3>تعداد درخواست‌ها زیاد است</h3>", 429)
    data = await request.post()
    token = str(data.get("t", ""))
    result = await asyncio.to_thread(ev.confirm_token_sync, token)
    if not result:
        return _page("لینک نامعتبر", "<h3>❌ لینک نامعتبر، منقضی یا قبلاً استفاده شده</h3>", 400)

    tg_id, email = result
    bot = request.app.get("bot")
    if bot:
        try:
            await bot.send_message(
                chat_id=tg_id,
                text=f"✅ ایمیل {ev.mask_email(email)} تایید شد.",
            )
        except Exception as e:
            logger.warning("Could not notify tg=%s: %s", tg_id, e)
    return _page("تایید شد", "<h3>✅ ایمیل تایید شد</h3><p>می‌توانی به تلگرام برگردی.</p>")


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_verify_server(bot=None) -> web.AppRunner:
    ev.init_tables()
    app = web.Application(client_max_size=4096)
    app["bot"] = bot
    app.add_routes([web.get("/verify", verify_get), web.post("/verify", verify_post),
                    web.get("/healthz", health)])
    runner = web.AppRunner(app, access_log=None)  # URL شامل توکن است؛ access log خاموش
    await runner.setup()
    host = os.environ.get("VERIFY_HOST", "127.0.0.1")
    port = int(os.environ.get("VERIFY_PORT", "8080"))
    await web.TCPSite(runner, host, port).start()
    logger.info("Verify server listening on %s:%d", host, port)
    return runner
