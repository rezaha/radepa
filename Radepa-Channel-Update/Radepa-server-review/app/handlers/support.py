# === app/handlers/support.py ===
from __future__ import annotations
from telegram import Update, ForceReply
from telegram.ext import ContextTypes
from app.config import config
from app.db.repos import UserRepo
from app.utils.keyboards import back_to_main_keyboard, main_menu_keyboard
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)


async def support_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کاربر دکمه 'ارتباط با ادمین' رو زد."""
    query = update.callback_query
    if not query: return
    await query.answer()
    context.user_data["awaiting_support_message"] = True
    await query.edit_message_text(
        "📩 *ارتباط با ادمین*\n\n"
        "پیام یا مشکل خودت رو بنویس — بلافاصله به ادمین ارسال میشه.\n\n"
        "_(برای لغو، /start بزن)_",
        parse_mode="Markdown",
        reply_markup=back_to_main_keyboard(),
    )


async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت پیام کاربر و ارسال به ادمین‌ها."""
    if not context.user_data.get("awaiting_support_message"): return
    user = update.effective_user
    if not user or not update.message or not update.message.text: return

    context.user_data.pop("awaiting_support_message", None)
    msg_text = update.message.text.strip()

    # اطلاع‌رسانی به همه ادمین‌ها
    for admin_id in config.admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"📩 *پیام پشتیبانی جدید*\n\n"
                    f"👤 کاربر: {user.first_name} (@{user.username or '—'})\n"
                    f"🆔 شناسه: `{user.id}`\n\n"
                    f"💬 پیام:\n{msg_text}"
                ),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.error("Failed to forward support msg to admin %d: %s", admin_id, exc)

    await update.message.reply_text(
        "✅ پیامت به ادمین ارسال شد!\nبه زودی پاسخ دریافت می‌کنی 🙏",
        reply_markup=main_menu_keyboard(),
    )
    logger.info("Support message from user=%d forwarded to admins", user.id)