"""Admin-only, read-only Instagram recovery page diagnostics."""
from __future__ import annotations

import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from app.config import config
from app.services.instagram_page_inspector import inspect_recovery_page

_lock = asyncio.Lock()


async def instagram_inspect_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    if user.id not in config.admin_ids or update.effective_chat.type != "private":
        await message.reply_text("این دستور فقط برای مدیر در گفت‌وگوی خصوصی فعال است.")
        return
    if _lock.locked():
        await message.reply_text("یک بررسی دیگر در حال اجراست.")
        return
    async with _lock:
        try:
            result = await asyncio.wait_for(inspect_recovery_page(), timeout=45)
        except (Exception, asyncio.TimeoutError) as exc:
            await message.reply_text(f"بررسی صفحه انجام نشد: {type(exc).__name__}")
            return
    await message.reply_text(
        "وضعیت صفحه بازیابی اینستاگرام (بدون ارسال نام کاربری):\n"
        f"وضعیت: {result['status']}\n"
        f"HTTP: {result.get('http_status', '-')}\n"
        f"تعداد فیلدها: {result.get('username_fields', '-')}\n"
        f"دکمه ادامه: {result.get('continue_buttons', '-')}"
    )
