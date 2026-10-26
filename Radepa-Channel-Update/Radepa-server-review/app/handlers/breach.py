"""Direct single-email lookups of public breach metadata; no SMTP or ownership gate."""
from __future__ import annotations

import html
import time

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.db.repos import OrderRepo, UserRepo
from app.services.leakcheck_public import BreachSummary, LeakCheckPublic, LeakCheckUnavailable
from app.utils.email_utils import mask_email, normalize_email

EMAIL_BUTTON = "📧 بررسی ایمیل"
_MENU_TEXTS = {EMAIL_BUTTON, "🔍 تحلیل آیدی", "💳 خرید اشتراک", "👤 حساب من",
               "📩 پشتیبانی", "⚙️ پنل ادمین"}
_OTHER_INPUTS = ("awaiting_instagram_username", "awaiting_support_message",
                 "adm_await", "rejecting_order_id")


async def clear_pending_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any new command or inline action leaves the previous email prompt."""
    context.user_data.pop("awaiting_breach_email", None)
    context.user_data.pop("awaiting_verify_email", None)


async def _allowed(update: Update) -> bool:
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return False
    if msg.chat.type != "private":
        await msg.reply_text("این بررسی فقط در گفت‌وگوی خصوصی انجام می‌شود.")
        return False
    account = UserRepo.get_by_telegram_id(user.id)
    if account and account.get("is_blocked"):
        await msg.reply_text("این حساب غیرفعال است.")
        return False
    return True


async def email_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update):
        return
    for key in (*_OTHER_INPUTS, "awaiting_verify_email"):
        context.user_data.pop(key, None)
    context.user_data["awaiting_breach_email"] = True
    await update.effective_message.reply_text(
        "📧 یک ایمیل بفرست تا خلاصه نشت‌های گزارش‌شده را بررسی کنم.\n"
        "نیازی به لینک تأیید نیست. خروجی شامل منابع نشت و نوع داده‌های افشاشده است."
    )


async def email_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    await email_prompt(update, context)


def format_summary(email: str, result: BreachSummary) -> str:
    lines = [f"🔐 گزارش نشت برای {html.escape(mask_email(email))}",
             f"تعداد رکوردهای گزارش‌شده: {result.found}"]
    if result.found == 0:
        lines.append("در این منبع رکوردی پیدا نشد؛ این نتیجه نبودن نشت در منابع دیگر را تضمین نمی‌کند.")
    if result.fields:
        lines.append("نوع داده‌های در معرض نشت: " + html.escape(", ".join(result.fields)[:800]))
    if result.sources:
        lines.append("منابع گزارش‌شده:")
        lines.extend(f"• {html.escape(name)} ({html.escape(date)})" for name, date in result.sources[:12])
    if len(result.sources) > 12:
        lines.append("برای کوتاه بودن پیام، حداکثر ۱۲ منبع نمایش داده شد.")
    lines.extend([
        "وجود نتیجه، هویت صاحب ایمیل یا وضعیت فعلی حساب را ثابت نمی‌کند.",
        "برای ایمیل خودت، گذرواژه‌های تکراری را عوض کن و تأیید دومرحله‌ای را فعال کن.",
        '<a href="https://leakcheck.io">Powered by LeakCheck</a>',
    ])
    return "\n".join(lines)


async def _lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str) -> bool:
    if not await _allowed(update):
        return True
    msg = update.effective_message
    email = normalize_email(raw)
    if not email:
        await msg.reply_text("فرمت ایمیل معتبر نیست؛ فقط یک ایمیل بفرست. مثال: name@example.com")
        return False
    now = time.monotonic()
    if now - context.user_data.get("breach_last_request", float("-inf")) < 5:
        await msg.reply_text("بین بررسی‌ها حداقل ۵ ثانیه فاصله بگذار.")
        return False
    context.user_data["breach_last_request"] = now
    service: LeakCheckPublic = context.bot_data["leakcheck_public"]
    try:
        result = await service.lookup_email(email)
    except LeakCheckUnavailable:
        await msg.reply_text("سرویس بررسی نشت اکنون در دسترس نیست؛ کمی بعد دوباره تلاش کن.")
        return False
    await msg.reply_text(format_summary(email, result), parse_mode="HTML", disable_web_page_preview=True)
    return True


async def breach_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_verify_email", None)
    if not context.args:
        await email_prompt(update, context)
    elif len(context.args) != 1:
        if await _allowed(update):
            await update.effective_message.reply_text("فرمت: /email name@example.com — هر بار فقط یک ایمیل.")
    elif await _lookup(update, context, context.args[0]):
        context.user_data.pop("awaiting_breach_email", None)


async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, user = update.effective_message, update.effective_user
    if not msg or not user or not msg.text:
        return
    raw = msg.text.strip()
    if raw in _MENU_TEXTS:
        context.user_data.pop("awaiting_breach_email", None)
        context.user_data.pop("awaiting_verify_email", None)
        return
    waiting = context.user_data.get("awaiting_breach_email")
    if not waiting:
        if msg.chat.type != "private" or not normalize_email(raw):
            return
        # Preserve support messages, admin inputs, Instagram input and payment evidence.
        if any(context.user_data.get(key) for key in _OTHER_INPUTS):
            return
        if OrderRepo.get_latest_awaiting_payment(user.id):
            return
    if await _lookup(update, context, raw):
        context.user_data.pop("awaiting_breach_email", None)
    raise ApplicationHandlerStop
