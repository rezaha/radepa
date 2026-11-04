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
    if context.args:
        await message.reply_text("این دستور ورودی نمی‌پذیرد؛ فقط دسترسی به یک صفحه ثابت را بررسی می‌کند.")
        return
    if _lock.locked():
        await message.reply_text("یک بررسی دیگر در حال اجراست.")
        return
    async with _lock:
        try:
            result = await asyncio.wait_for(inspect_recovery_page(), timeout=45)
        except Exception as exc:
            await message.reply_text(f"بررسی صفحه انجام نشد: {type(exc).__name__}")
            return
    if result['status'] != 'ok':
        http = result.get('http_status')
        if http == 403:
            explanation = "درخواست صفحه با HTTP 403 رد شد؛ علت دقیق از این پاسخ مشخص نیست."
        elif http == 429:
            explanation = "درخواست با HTTP 429 محدود شد؛ بررسی را پشت‌سرهم تکرار نکنید."
        elif http is not None:
            explanation = f"صفحه پاسخ ناموفق HTTP {http} داد."
        else:
            explanation = "پاسخ قابل بررسی از صفحه دریافت نشد."
        await message.reply_text(
            "بررسی صفحه بازیابی اینستاگرام انجام نشد.\n"
            f"{explanation}\n"
            "ساختار فرم قابل ارزیابی نیست؛ تعداد فیلدها و دکمه‌ها گزارش نمی‌شود.\n"
            "این وضعیت نتیجه جست‌وجوی حساب یا نشانه نبود اطلاعات نیست؛ هیچ نام کاربری ارسال نشده است."
        )
        return
    await message.reply_text(
        "وضعیت صفحه بازیابی اینستاگرام (بدون ارسال نام کاربری):\n"
        f"وضعیت: {result['status']}\n"
        f"HTTP: {result.get('http_status', '-')}\n"
        f"تعداد فیلدها: {result.get('username_fields', '-')}\n"
        f"دکمه ادامه: {result.get('continue_buttons', '-')}"
    )
