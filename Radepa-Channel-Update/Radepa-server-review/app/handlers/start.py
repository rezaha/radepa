# === app/handlers/start.py ===
from __future__ import annotations

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import ContextTypes

from app.config import config
from app.db.repos import UserRepo
from app.handlers.breach import EMAIL_BUTTON, email_prompt
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)


# ─── Reply Keyboard ثابت (همیشه پایین صفحه) ──────────────────
def _persistent_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
    from app.config import config as _cfg
    is_admin = user_id in _cfg.admin_ids

    rows = [
        [KeyboardButton("🔍 تحلیل آیدی"), KeyboardButton("💳 خرید اشتراک")],
        [KeyboardButton("👤 حساب من"),    KeyboardButton("📩 پشتیبانی")],
        [KeyboardButton(EMAIL_BUTTON)],
        [KeyboardButton("📢 کانال اطلاع‌رسانی")],
    ]
    if is_admin:
        rows.append([KeyboardButton("⚙️ پنل ادمین")])

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="یه گزینه انتخاب کن یا ایمیل بفرست...",
    )
def _inline_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 تحلیل آیدی",    callback_data="menu:analyze"),
         InlineKeyboardButton("💳 خرید اشتراک",   callback_data="menu:plans")],
        [InlineKeyboardButton("👤 حساب من",        callback_data="menu:account"),
         InlineKeyboardButton("📩 پشتیبانی",       callback_data="menu:support")],
        [InlineKeyboardButton(EMAIL_BUTTON, callback_data="menu:email")],
        [InlineKeyboardButton("📢 کانال اطلاع‌رسانی", url="https://t.me/Radepa_Updates")],
    ])


# ─── /start ───────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_breach_email", None)
    context.user_data.pop("awaiting_verify_email", None)
    user = update.effective_user
    if not user:
        return

    # ثبت یا آپدیت کاربر در DB
    db_user = UserRepo.upsert(user.id, user.username, user.first_name or "کاربر")
    is_new  = db_user.get("credits", 0) == 0 and not db_user.get("subscription_expire_at")
    is_blocked = db_user.get("is_blocked", 0)

    if is_blocked:
        await update.message.reply_text(
            "⛔ حساب شما مسدود شده. برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
        )
        return

    bot_name = context.bot_data.get("bot_name", "ردپاگرد")
    name     = user.first_name or "دوست عزیز"

    if is_new:
        # کاربر جدید
        text = (
            f"سلام {name}! 👋\n\n"
            f"به *{bot_name}* خوش اومدی 🔍\n\n"
            "اینجا می‌تونی نتایج جست‌وجوی عمومی مرتبط با یک آیدی اینستاگرام رو ببینی.\n"
            "قطعه‌متن‌ها، نویسندگی کامنت یا هویت صاحب حساب را ثابت نمی‌کنند.\n\n"
            "📧 بررسی خلاصه نشت ایمیل رایگان است؛ روی «بررسی ایمیل» بزن.\n\n"
            "📌 *برای شروع:*\n"
            "۱. یه پلن بخر 👇\n"
            "۲. آیدی اینستاگرام مورد نظر رو بفرست\n"
            "۳. نتایج رو ببین!\n\n"
            "⚠️ تمام نتایج احتمالی و از منابع عمومی هستن."
        )
    else:
        # کاربر قدیمی
        credits = db_user.get("credits", 0)
        credit_txt = f"💎 {credits} تحلیل باقی‌مانده" if credits > 0 else "💳 اعتبارت تموم شده"
        text = (
            f"سلام {name}! 🙌\n\n"
            f"{credit_txt}\n\n"
            "چیکار می‌خوای بکنی؟"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=_persistent_keyboard(user.id),
    )

# ─── /help ────────────────────────────────────────────────────
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_name = context.bot_data.get("bot_name", "ردپاگرد")
    text = (
        f"📖 *راهنمای {bot_name}*\n\n"
        "*دستورات:*\n"
        "/start — منوی اصلی\n"
        "/analyze — تحلیل آیدی اینستاگرام\n"
        "/email — دریافت ایمیل و بررسی مستقیم نشت (رایگان)\n"
        "/breach email@example.com — بررسی مستقیم یک ایمیل\n"
        "/account — مشاهده حساب و اعتبار\n"
        "/plans — خرید اشتراک\n"
        "/help — این راهنما\n"
        "/channel — لینک کانال رسمی\n\n"
        "*نحوه استفاده:*\n"
        "۱. پلن مناسب رو بخر\n"
        "۲. روی 🔍 تحلیل آیدی بزن\n"
        "۳. آیدی اینستاگرام رو بفرست (بدون @)\n"
        "۴. چند ثانیه صبر کن و نتیجه رو ببین\n\n"
        "⚠️ نتایج جست‌وجو احتمالی‌اند و نویسندگی کامنت را ثابت نمی‌کنند."
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=_inline_main_menu())


# ─── /analyze (shortcut) ──────────────────────────────────────
async def analyze_shortcut_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    db_user = UserRepo.get_by_telegram_id(user.id)
    if not db_user:
        await update.message.reply_text("اول /start بزن.")
        return
    if db_user.get("is_blocked"):
        await update.message.reply_text("⛔ حساب شما مسدود شده.")
        return
    context.user_data["awaiting_instagram_username"] = True
    await update.message.reply_text(
        "🔍 آیدی اینستاگرام مورد نظر رو بفرست (بدون @):\n\n"
        "مثال: `username`",
        parse_mode="Markdown",
    )


# ─── /account (shortcut) ──────────────────────────────────────
async def account_shortcut_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # فوروارد به account handler
    from app.handlers.account import account_callback
    # simulate callback با message
    user = update.effective_user
    if not user:
        return
    db_user = UserRepo.get_by_telegram_id(user.id)
    if not db_user:
        await update.message.reply_text("اول /start بزن.")
        return
    from app.utils.time_utils import format_shamsi_approx, is_expired
    credits = db_user.get("credits", 0)
    expire  = db_user.get("subscription_expire_at")
    expired = is_expired(expire)
    status  = "✅ فعال" if (credits > 0 and not expired) else "❌ منقضی یا بدون اعتبار"
    text = (
        f"👤 *حساب من*\n\n"
        f"نام: {db_user.get('first_name','؟')}\n"
        f"💎 اعتبار: {credits}\n"
        f"📅 انقضا: {format_shamsi_approx(expire)}\n"
        f"وضعیت: {status}"
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=_inline_main_menu())


# ─── /plans (shortcut) ────────────────────────────────────────
async def plans_shortcut_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.handlers.plans import _send_plans
    await _send_plans(update.message, context)


# ─── callback منوی اصلی (inline) ─────────────────────────────
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_breach_email", None)
    query = update.callback_query
    if not query:
        return
    await query.answer()
    await query.edit_message_text("منوی اصلی:", reply_markup=_inline_main_menu())


# ─── مدیریت دکمه‌های Reply Keyboard ──────────────────────────
async def reply_keyboard_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """برمی‌گردونه True اگه پیام یکی از دکمه‌های Reply Keyboard بود."""
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()
    mapping = {
        EMAIL_BUTTON: "menu:email",
        "🔍 تحلیل آیدی":  "menu:analyze",
        "💳 خرید اشتراک": "menu:plans",
        "👤 حساب من":      "menu:account",
        "📩 پشتیبانی":     "menu:support",
    }
    if text == "📢 کانال اطلاع‌رسانی":
        await channel_command(update, context)
        return True

    if text == "⚙️ پنل ادمین":
        from app.handlers.admin import admin_command
        await admin_command(update, context)
        return True

    if text not in mapping:
        return False
    cb = mapping[text]
    if cb == "menu:email":
        await email_prompt(update, context)
    elif cb == "menu:analyze":
        context.user_data["awaiting_instagram_username"] = True
        await update.message.reply_text(
            "🔍 آیدی اینستاگرام مورد نظر رو بفرست (بدون @):\n\nمثال: `ronaldo`",
            parse_mode="Markdown",
        )
    elif cb == "menu:plans":
        from app.handlers.plans import _send_plans
        await _send_plans(update.message, context)
    elif cb == "menu:account":
        await account_shortcut_handler(update, context)
    elif cb == "menu:support":
        try:
            from app.handlers.support import support_prompt_callback
            context.user_data["awaiting_support_message"] = True
            await update.message.reply_text(
                "📩 پیامت رو بنویس، مستقیم به ادمین میرسه:"
            )
        except ImportError:
            await update.message.reply_text("📩 برای پشتیبانی با ادمین تماس بگیر.")
    return True


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provide a verified destination in a URL keyboard; no forced subscription."""
    await update.effective_message.reply_text(
        "📢 کانال رسمی اطلاع‌رسانی ردپا\n"
        "اخبار، تغییرات و اطلاعیه‌های ربات را اینجا دنبال کن:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 ورود به کانال ردپا", url="https://t.me/Radepa_Updates")
        ]]),
    )
