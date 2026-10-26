from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.db.repos import PlanRepo, UserRepo
from app.services.payment_service import PaymentService
from app.services.products import PRODUCTS
from app.utils.keyboards import plan_buy_keyboard, cancel_order_keyboard, back_to_main_keyboard
from app.config import config

TERMS = ("هر خرید فقط یک جست‌وجو، بدون انقضای زمانی و ویژه همان سرویس است.\n"
         "پاسخ موفق بدون نتیجه هم اعتبار مصرف می‌کند؛ خطای سرویس اعتبار را بازمی‌گرداند.\n"
         "ایمیل: خلاصه منابع نشت، پیام تلگرام و فایل TXT؛ بدون رمز یا شماره واقعی.\n"
         "اینستاگرام: شواهد و قطعه‌متن‌های عمومی؛ دسترسی به حساب خصوصی یا همه کامنت‌ها تضمین نمی‌شود.")

def plan_text(plan):
    return f"{plan['title']}\n💰 {plan['price_toman']:,} تومان | یک جست‌وجو\n\n" + TERMS

async def show_plans_callback(update, context):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    plans = [p for p in PlanRepo.get_active() if p["plan_code"] in PRODUCTS]
    text = "💳 خرید جست‌وجو\n\n" + "\n".join(
        f"• {p['title']}: {p['price_toman']:,} تومان" for p in plans) + "\n\n" + TERMS
    keyboard = [[InlineKeyboardButton(p["title"], callback_data=f"buy:{p['plan_code']}")] for p in plans]
    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu:main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def _send_plans(message, context):
    for plan in PlanRepo.get_active():
        if plan["plan_code"] in PRODUCTS:
            await message.reply_text(plan_text(plan), reply_markup=plan_buy_keyboard(plan["plan_code"]))

async def buy_plan_callback(update, context):
    query, user = update.callback_query, update.effective_user
    if not query or not user:
        return
    await query.answer()
    if update.effective_chat.type != "private":
        await query.edit_message_text("برای خرید به گفت‌وگوی خصوصی ربات بروید.")
        return
    account = UserRepo.get_by_telegram_id(user.id)
    if not account:
        UserRepo.upsert(user.id, user.username, user.first_name or "کاربر")
    elif account.get("is_blocked"):
        await query.edit_message_text("این حساب غیرفعال است.")
        return
    code = (query.data or "").split(":", 1)[-1]
    plan = PlanRepo.get(code)
    if code not in PRODUCTS or not plan or not plan["is_active"]:
        await query.edit_message_text("این محصول دیگر قابل خرید نیست؛ /plans را بزنید.")
        return
    order = PaymentService.create_order(user.id, code)
    if not order:
        await query.edit_message_text("سفارش قبلی در انتظار پرداخت یا بررسی دارید؛ ابتدا آن را تکمیل یا لغو کنید.",
                                      reply_markup=back_to_main_keyboard())
        return
    context.user_data["pending_order_id"] = order["order_id"]
    await query.edit_message_text(
        f"💳 <b>پرداخت یک جست‌وجو</b>\n\nسرویس: {escape(plan['title'])}\n"
        f"مبلغ: <b>{order['amount_toman']:,} تومان</b>\n"
        f"شماره کارت: <code>{escape(config.payment_card_number)}</code>\n"
        f"به نام: {escape(config.payment_card_holder)}\n"
        f"شناسه سفارش: <code>{order['order_id']}</code>\n\n"
        "پس از واریز، عکس رسید یا شناسه تراکنش را بفرستید.\n\n" + TERMS,
        parse_mode="HTML", reply_markup=cancel_order_keyboard(order["order_id"]))
