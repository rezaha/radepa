"""Direct single-email lookups of public breach metadata; no SMTP or ownership gate."""
from __future__ import annotations

import time

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.db.repos import OrderRepo, UserRepo
from app.utils.keyboards import account_keyboard
from app.services.leakcheck_public import BreachSummary, LeakCheckPublic, LeakCheckUnavailable
from app.utils.email_utils import normalize_email

EMAIL_BUTTON = "📧 بررسی ایمیل"
_MENU_TEXTS = {EMAIL_BUTTON, "🔍 تحلیل آیدی", "💳 خرید اشتراک", "👤 حساب من",
               "🔎 تحلیل اینستاگرام", "🧾 سفارش‌های من", "📩 پشتیبانی", "⚙️ پنل ادمین", "📖 راهنمای استفاده", "💳 خرید جست‌وجو", "📢 کانال اطلاع‌رسانی"}
_OTHER_INPUTS = ("awaiting_instagram_username", "awaiting_support_message",
                 "adm_await", "rejecting_order_id")


async def clear_pending_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any new command or inline action leaves the previous email prompt."""
    context.user_data.pop("awaiting_breach_email", None)
    context.user_data.pop("awaiting_verify_email", None)
    context.user_data.pop("awaiting_instagram_username", None)
    context.user_data.pop("awaiting_support_message", None)


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
        "هر بررسی یک اعتبار ایمیل مصرف می‌کند؛ قیمت: ۱۹۹٬۰۰۰ تومان.\n"
        "پاسخ موفق بدون نتیجه هم یک بررسی است؛ خطای سرویس اعتبار مصرف نمی‌کند.\n"
        "نیازی به لینک تأیید نیست. خروجی شامل منابع نشت، ریسک، کیفیت و قابلیت تحویل ایمیل است.\n"
        "ایمیل هدف و وضعیت بررسی برای رسیدگی، در تاریخچه حساب قابل مشاهده برای مدیر ثبت می‌شود."
    )


async def email_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    await email_prompt(update, context)


def format_summary(email: str, result: BreachSummary) -> str:
    from app.services.email_report import render_html
    return render_html(email, result)


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
    from io import BytesIO
    from telegram.error import TelegramError
    from app.services.credit_service import CreditService
    from app.services.email_report import render_txt
    charge_id = CreditService.reserve(update.effective_user.id, "email")
    if not charge_id:
        await msg.reply_text("اعتبار بررسی ایمیل ندارید یا بررسی قبلی هنوز در حال اجراست.\n"
                             "از «خرید جست‌وجو» اعتبار یک بررسی ایمیل تهیه کنید: ۱۹۹٬۰۰۰ تومان.",
                             reply_markup=account_keyboard())
        return False
    service: LeakCheckPublic = context.bot_data["leakcheck_public"]
    history_id = None
    from app.db.repos import SearchHistoryRepo
    try:
        history_id = SearchHistoryRepo.start_email(update.effective_user.id, email)
        from app.services.email_lookup import lookup_email
        result = await lookup_email(email, service, context.bot_data.get("abstract_email"))
        await msg.reply_text(format_summary(email, result), parse_mode="HTML", disable_web_page_preview=True)
        with BytesIO(render_txt(email, result).encode("utf-8")) as document:
            await msg.reply_document(document=document, filename="email-security-report.txt",
                                     caption="📄 گزارش امنیت ایمیل | ردپا — یک جست‌وجو انجام شد.")
        SearchHistoryRepo.finish_email(history_id, "done")
        CreditService.complete(charge_id)
        return True
    except LeakCheckUnavailable:
        await msg.reply_text("هیچ‌کدام از سرویس‌های بررسی ایمیل اکنون در دسترس نیست؛ اعتبار این بررسی بازگردانده می‌شود.")
        return False
    except TelegramError:
        # Do not log token-bearing exceptions or retain the report on disk.
        return False
    finally:
        CreditService.refund(charge_id)
        if history_id is not None:
            SearchHistoryRepo.finish_email(history_id, "failed")


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
