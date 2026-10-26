from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from app.config import config

CHANNEL_USERNAME = "@Radepa_Updates"

async def channel_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only count of Telegram channel subscribers, not bot monthly users."""
    user = update.effective_user
    if not user or user.id not in config.admin_ids:
        return
    try:
        count = await context.bot.get_chat_member_count(CHANNEL_USERNAME)
    except TelegramError:
        await update.effective_message.reply_text(
            "آمار کانال در دسترس نیست. شناسه کانال و دسترسی ربات را بررسی کن."
        )
        return
    await update.effective_message.reply_text(
        f"📢 کانال ردپا: {count:,} عضو\n"
        "https://t.me/Radepa_Updates\n\n"
        "این عدد تعداد اعضای کانال است، نه کاربران ماهانه ربات."
    )
