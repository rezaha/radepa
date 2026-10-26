from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from app.db.repos import UserRepo
from app.utils.texts_fa import ACCOUNT_INFO, BLOCKED
from app.utils.keyboards import account_keyboard
from app.utils.time_utils import format_shamsi_approx, days_remaining

async def account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    user = update.effective_user
    if not user: return
    db_user = UserRepo.get_by_telegram_id(user.id)
    if not db_user or db_user.get("is_blocked"):
        await query.edit_message_text(BLOCKED); return
    expire = db_user.get("subscription_expire_at")
    await query.edit_message_text(ACCOUNT_INFO.format(
        first_name=db_user["first_name"], credits=db_user["credits"],
        expire=format_shamsi_approx(expire), days_left=days_remaining(expire)),
        parse_mode="Markdown", reply_markup=account_keyboard())
