"""Persisted receipts rendered consistently in notifications and admin panels."""
from telegram.error import TelegramError
from app.db.repos import PlanRepo, UserRepo
from app.utils.keyboards import admin_review_keyboard, back_to_main_keyboard


def clipped(text, units):
    return str(text).encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")


def receipt_text(order):
    user = UserRepo.get_by_telegram_id(order["telegram_user_id"]) or {}
    plan = PlanRepo.get(order["plan_code"]) or {}
    text = (f"🧾 رسید پرداخت\nسفارش: {order['order_id']}\n"
            f"کاربر: {clipped(user.get('first_name') or '—', 80)}\n"
            f"شناسه تلگرام: {order['telegram_user_id']}\n"
            f"نام کاربری: {clipped(user.get('username') or '—', 40)}\n"
            f"سرویس: {clipped(plan.get('title') or order['plan_code'], 100)}\n"
            f"مبلغ: {order['amount_toman']:,} تومان\nوضعیت: {order['status']}")
    if order.get("evidence_text"):
        text += "\nشناسه تراکنش / توضیح رسید: " + clipped(order['evidence_text'], 2000)
    return clipped(text, 3800)


async def send_order_review(bot, admin_id, order):
    text = receipt_text(order)
    keyboard = (admin_review_keyboard(order['order_id']) if order['status'] == 'awaiting_review'
                else back_to_main_keyboard())
    media = order.get('evidence_file_id')
    if media and order.get('evidence_type') in ('photo', 'document'):
        try:
            if order['evidence_type'] == 'photo':
                await bot.send_photo(chat_id=admin_id, photo=media, caption=clipped(text, 950),
                                     parse_mode=None, reply_markup=keyboard)
            else:
                await bot.send_document(chat_id=admin_id, document=media, caption=clipped(text, 950),
                                        parse_mode=None, reply_markup=keyboard)
            return True
        except TelegramError:
            # File failure must not conceal the persisted order; do not expose exception URLs.
            text = "⚠️ دریافت تصویر رسید از تلگرام ناموفق بود؛ تصویر را پیش از تأیید بررسی کنید.\n\n" + text
    await bot.send_message(chat_id=admin_id, text=clipped(text, 3900), parse_mode=None, reply_markup=keyboard)
    return not media


async def edit_review(query, text, **kwargs):
    message = getattr(query, 'message', None)
    if message and (getattr(message, 'photo', None) or getattr(message, 'document', None)):
        await query.edit_message_caption(caption=text, **kwargs)
    else:
        await query.edit_message_text(text, **kwargs)
