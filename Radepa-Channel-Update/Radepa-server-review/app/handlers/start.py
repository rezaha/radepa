from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from app.db.repos import UserRepo
from app.handlers.breach import EMAIL_BUTTON, email_prompt
from app.utils.keyboards import main_menu_keyboard, back_to_main_keyboard, INSTAGRAM_BUTTON, ORDERS_BUTTON
from app.handlers.plans import orders_handler
from app.handlers.account import account_text

HELP_BUTTON = "📖 راهنمای استفاده"
BUY_BUTTON = "💳 خرید جست‌وجو"

HELP_TEXT = """📖 راهنمای استفاده از ردپا

۱. با /start شروع کنید و از «خرید جست‌وجو» سرویس موردنظر را انتخاب کنید:
📧 یک بررسی ایمیل: ۱۹۹٬۰۰۰ تومان
🔎 یک تحلیل اینستاگرام: ۲۹۹٬۰۰۰ تومان
۲. مبلغ سفارش را واریز کنید و عکس رسید یا شناسه تراکنش را در همین گفت‌وگو بفرستید. پس از تأیید ادمین، اعتبار همان سرویس فعال می‌شود.
برای ادامه پرداخت، لغو سفارش پرداخت‌نشده یا پیگیری رسید، «سفارش‌های من» یا /orders را بزنید.
۳. برای ایمیل، «بررسی ایمیل» یا /email name@example.com را بزنید. برای اینستاگرام، «تحلیل اینستاگرام» یا /analyze را بزنید و یک آیدی مثل example_user بفرستید.
۴. گزارش ایمیل در تلگرام و فایل TXT ارسال می‌شود. نتایج اینستاگرام بخش‌های خلاصه، لینک‌ها و قطعه‌متن‌ها دارند.

💎 اعتبارها جدا و بدون انقضای زمانی‌اند. هر پاسخ موفق حتی بدون نتیجه، یک اعتبار مصرف می‌کند. خطای سرویس اعتبار را بازمی‌گرداند. اعتبارهای قدیمی اینستاگرام شرایط قبلی خود را دارند.
⚠️ نبود نتیجه تضمین امنیت نیست. مشاهده ایمیل در نشت، افشای رمز فعلی را اثبات نمی‌کند. API عمومی، خود رمز و شماره تلفن را نمایش نمی‌دهد.
🔐 رمزهای تکراری را با رمز قوی و منحصربه‌فرد عوض کنید و تأیید دومرحله‌ای را فعال کنید.
🔎 اینستاگرام فقط از منابع عمومی جست‌وجو می‌شود؛ همه کامنت‌ها یا حساب خصوصی قابل تضمین نیست و قطعه‌متن، نویسندگی کامنت را ثابت نمی‌کند.

دستورات:
/start — منوی اصلی
/plans — خرید جست‌وجو
ایمیل یا آیدی هدف و وضعیت جست‌وجو برای رسیدگی در تاریخچه حساب قابل مشاهده برای مدیر ثبت می‌شود.

/orders — پیگیری سفارش و ادامه پرداخت
/account — موجودی اعتبار
/email — بررسی یک ایمیل
/breach — همان بررسی ایمیل
/analyze — تحلیل اینستاگرام
/help — راهنما
/channel — کانال رسمی
📩 برای مشکل پرداخت یا استفاده، «پشتیبانی» را بزنید.
"""

def _persistent_keyboard(user_id=0):
    from app.config import config
    rows = [[EMAIL_BUTTON, INSTAGRAM_BUTTON], [BUY_BUTTON, ORDERS_BUTTON],
            ["👤 حساب من", HELP_BUTTON], ["📩 پشتیبانی", "📢 کانال اطلاع‌رسانی"]]
    if user_id in config.admin_ids:
        rows.append(["⚙️ پنل ادمین"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

def _inline_main_menu():
    return main_menu_keyboard()

def _clear_input(context):
    for key in ("rejecting_order_id", "adm_reject_order_id", "awaiting_breach_email", "awaiting_verify_email", "awaiting_instagram_username",
                "awaiting_support_message", "adm_await", "rejecting_order_id"):
        context.user_data.pop(key, None)

async def start_handler(update, context):
    _clear_input(context)
    user = update.effective_user
    if not user:
        return
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("برای استفاده، گفت‌وگوی خصوصی ربات را باز کنید.")
        return
    account = UserRepo.upsert(user.id, user.username, user.first_name or "کاربر")
    if account.get("is_blocked"):
        await update.message.reply_text("حساب شما غیرفعال است؛ با پشتیبانی تماس بگیرید.")
        return
    await update.message.reply_text(
        f"سلام {user.first_name or 'دوست عزیز'}! 👋\n\nبه ردپا خوش آمدید.\n"
        "📧 بررسی خلاصه نشت یک ایمیل: ۱۹۹٬۰۰۰ تومان\n"
        "🔎 تحلیل ردپای عمومی یک آیدی اینستاگرام: ۲۹۹٬۰۰۰ تومان\n\n"
        "هر خرید فقط یک جست‌وجو برای همان سرویس است. از خرید جست‌وجو یا راهنمای استفاده شروع کنید.\n\n"
        + account_text(account), reply_markup=_persistent_keyboard(user.id))

async def help_handler(update, context):
    _clear_input(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(HELP_TEXT, reply_markup=back_to_main_keyboard())
    else:
        await update.effective_message.reply_text(HELP_TEXT, reply_markup=_inline_main_menu())

async def analyze_shortcut_handler(update, context):
    from app.services.subscription_service import SubscriptionService
    from app.utils.texts_fa import NO_CREDITS, BLOCKED
    user = update.effective_user
    if not user:
        return
    _clear_input(context)
    can, reason = SubscriptionService.check_can_analyze(user.id)
    if not can:
        await update.effective_message.reply_text(BLOCKED if reason == "blocked" else NO_CREDITS,
                                                  reply_markup=main_menu_keyboard())
        return
    context.user_data["awaiting_instagram_username"] = True
    await update.effective_message.reply_text("🔎 یک آیدی اینستاگرام بفرستید؛ مثال: example_user\n"
        "یک اعتبار اینستاگرام مصرف می‌شود؛ یافتن همه کامنت‌ها تضمین نمی‌شود.")

async def account_shortcut_handler(update, context):
    user = update.effective_user
    account = UserRepo.get_by_telegram_id(user.id) if user else None
    await update.effective_message.reply_text(account_text(account) if account and not account.get("is_blocked")
                                              else "ابتدا /start را بزنید یا با پشتیبانی تماس بگیرید.",
                                              reply_markup=_inline_main_menu())

async def plans_shortcut_handler(update, context):
    from app.handlers.plans import _send_plans
    _clear_input(context)
    await _send_plans(update.effective_message, context)

async def main_menu_callback(update, context):
    _clear_input(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("منوی اصلی:", reply_markup=_inline_main_menu())
    elif update.effective_message:
        await update.effective_message.reply_text("عملیات ورودی لغو شد. منوی اصلی:", reply_markup=_inline_main_menu())

async def reply_keyboard_router(update, context):
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()
    routes = {EMAIL_BUTTON: email_prompt, "🔍 تحلیل آیدی": analyze_shortcut_handler,
              INSTAGRAM_BUTTON: analyze_shortcut_handler, ORDERS_BUTTON: orders_handler,
              BUY_BUTTON: plans_shortcut_handler, "💳 خرید اشتراک": plans_shortcut_handler,
              "👤 حساب من": account_shortcut_handler, HELP_BUTTON: help_handler,
              "📢 کانال اطلاع‌رسانی": channel_command}
    if text in routes:
        _clear_input(context)
        await routes[text](update, context)
        return True
    if text == "📩 پشتیبانی":
        _clear_input(context)
        context.user_data["awaiting_support_message"] = True
        await update.message.reply_text("📩 پیام خود را بنویسید تا به پشتیبانی ارسال شود.")
        return True
    if text == "⚙️ پنل ادمین":
        _clear_input(context)
        from app.handlers.admin import admin_command
        await admin_command(update, context)
        return True
    return False

async def channel_command(update, context):
    await update.effective_message.reply_text("📢 کانال رسمی اطلاع‌رسانی ردپا",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ورود به کانال", url="https://t.me/Radepa_Updates")]]))
