from telegram import Update
from telegram.ext import ContextTypes
from app.db.repos import UserRepo
from app.utils.keyboards import account_keyboard
from app.utils.time_utils import format_shamsi_approx
from app.utils.texts_fa import BLOCKED

def account_text(user):
    return ("👤 حساب من\n\n"
            f"📧 اعتبار بررسی ایمیل: {user.get('email_credits', 0)} جست‌وجو\n"
            f"🔎 اعتبار اینستاگرام: {user.get('instagram_credits', 0)} جست‌وجو\n"
            "اعتبارهای جدید بدون انقضای زمانی و فقط برای سرویس خریداری‌شده هستند.\n\n"
            f"اعتبار قدیمی اینستاگرام: {user.get('credits', 0)}\n"
            f"انقضای اعتبار قدیمی: {format_shamsi_approx(user.get('subscription_expire_at'))}")

async def account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    user = UserRepo.get_by_telegram_id(update.effective_user.id)
    await query.edit_message_text(account_text(user) if user and not user.get("is_blocked") else BLOCKED,
                                  reply_markup=account_keyboard())
