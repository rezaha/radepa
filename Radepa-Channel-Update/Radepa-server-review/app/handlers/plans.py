"""Two-product checkout with an actionable, ownership-checked order recovery flow."""
from html import escape
from telegram.error import BadRequest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.db.repos import PlanRepo, UserRepo, OrderRepo
from app.services.payment_service import PaymentService
from app.services.products import PRODUCTS, EMAIL_PLAN, INSTAGRAM_PLAN
from app.utils.keyboards import back_to_main_keyboard
from app.config import config

TERMS = ("هر خرید فقط یک جست‌وجو، بدون انقضای زمانی و ویژه همان سرویس است.\n"
         "پاسخ موفق بدون نتیجه هم اعتبار مصرف می‌کند؛ خطای سرویس اعتبار را بازمی‌گرداند.\n"
         "هدف و وضعیت جست‌وجو در تاریخچه حساب، قابل مشاهده برای مدیر، ثبت می‌شود.")


def catalog():
    plans = [PlanRepo.get(code) for code in PRODUCTS]
    plans = [p for p in plans if p and p['is_active']]
    lines = ["💳 <b>انتخاب سرویس</b>", ""]
    descriptions = {
        EMAIL_PLAN: "📧 خلاصه منابع نشت + راهکارهای امنیتی\n📄 گزارش تلگرام و فایل TXT؛ بدون رمز و شماره واقعی",
        INSTAGRAM_PLAN: "🔎 لینک‌ها و قطعه‌متن‌های مرتبط با آیدی\n🌐 فقط داده‌های عمومی؛ بدون تضمین همه کامنت‌ها یا حساب خصوصی",
    }
    rows = []
    for plan in plans:
        code = plan['plan_code']
        lines += [f"<b>{escape(plan['title'])}</b>", descriptions[code],
                  f"💰 {plan['price_toman']:,} تومان | یک جست‌وجو", ""]
        short = "📧 خرید بررسی ایمیل" if code == EMAIL_PLAN else "🔎 خرید تحلیل اینستاگرام"
        rows.append([InlineKeyboardButton(f"{short} · {plan['price_toman']:,} تومان", callback_data=f"buy:{code}")])
    if not plans:
        lines.append("در حال حاضر خرید سرویس فعال نیست.")
    lines += [TERMS]
    rows += [[InlineKeyboardButton("🧾 سفارش‌های من", callback_data="orders:list")],
             [InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu:main")]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def show_plans_callback(update, context):
    if update.callback_query:
        await update.callback_query.answer()
        text, keyboard = catalog()
        await _edit(update.callback_query, text, parse_mode="HTML", reply_markup=keyboard)


async def _send_plans(message, context):
    text, keyboard = catalog()
    await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _account_allowed(update):
    user = update.effective_user
    if not user or update.effective_chat.type != "private":
        return False
    account = UserRepo.get_by_telegram_id(user.id)
    return not account or not account.get('is_blocked')


def order_view(order, requested_code=None):
    plan = PlanRepo.get(order['plan_code'])
    title = plan['title'] if plan else order['plan_code']
    lines = ["🧾 <b>سفارش شما</b>", f"سرویس: {escape(title)}",
             f"مبلغ: <b>{order['amount_toman']:,} تومان</b>",
             f"شناسه: <code>{escape(order['order_id'])}</code>", ""]
    rows = []
    if order['status'] == 'awaiting_payment':
        if requested_code and requested_code != order['plan_code']:
            lines += ["یک سفارش پرداخت‌نشده برای سرویس دیگری دارید.",
                      "می‌توانید پرداخت آن را ادامه دهید یا با دکمه زیر آن را لغو و سرویس جدید را انتخاب کنید.", ""]
        lines += ["💳 <b>در انتظار پرداخت</b>",
                  f"شماره کارت: <code>{escape(config.payment_card_number)}</code>",
                  f"به نام: {escape(config.payment_card_holder)}", "",
                  "اگر قبلاً واریز کرده‌اید، دوباره پرداخت نکنید؛ رسید همان واریز را بفرستید.",
                  "عکس رسید یا شناسه تراکنش را در همین گفت‌وگو ارسال کنید.", "", TERMS]
        if requested_code in PRODUCTS and requested_code != order['plan_code']:
            selected = PlanRepo.get(requested_code)
            if selected and selected['is_active']:
                label = 'ایمیل' if requested_code == EMAIL_PLAN else 'اینستاگرام'
                rows.append([InlineKeyboardButton(f"🔄 لغو سفارش قبلی و خرید {label}",
                    callback_data=f"orders:switch:{order['order_id']}:{requested_code}")])
        rows.append([InlineKeyboardButton("❌ لغو این سفارش", callback_data=f"cancel_order:{order['order_id']}")])
    elif order['status'] == 'awaiting_review':
        lines += ["⏳ <b>رسید دریافت شده؛ در انتظار تأیید ادمین</b>",
                  "دوباره واریز نکنید. پس از تأیید، اعتبار همین سرویس اضافه می‌شود.",
                  "تغییر یا لغو سفارش دارای رسید از این بخش امکان‌پذیر نیست؛ برای اصلاح با پشتیبانی تماس بگیرید."]
        rows.append([InlineKeyboardButton("🔄 به‌روزرسانی وضعیت", callback_data=f"orders:view:{order['order_id']}")])
    else:
        status = {'paid': '✅ پرداخت تأیید شده', 'rejected': '❌ پرداخت رد شده', 'expired': 'سفارش لغو یا منقضی شده'}.get(order['status'], order['status'])
        lines += [escape(status), "برای مشاهده اعتبار، «حساب من» را بزنید."]
        rows.append([InlineKeyboardButton("👤 حساب من", callback_data="menu:account")])
    rows += [[InlineKeyboardButton("🧾 سفارش‌های من", callback_data="orders:list"),
              InlineKeyboardButton("📩 پشتیبانی", callback_data="menu:support")],
             [InlineKeyboardButton("💳 انتخاب سرویس", callback_data="menu:plans")]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _show_order(query, context, order, requested_code=None):
    if order['status'] == 'awaiting_payment':
        context.user_data['pending_order_id'] = order['order_id']
    text, keyboard = order_view(order, requested_code)
    await _edit(query, text, parse_mode="HTML", reply_markup=keyboard)


async def buy_plan_callback(update, context):
    query, user = update.callback_query, update.effective_user
    if not query or not user:
        return
    await query.answer()
    if not await _account_allowed(update):
        await _edit(query, "خرید فقط برای حساب فعال و در گفت‌وگوی خصوصی ربات امکان‌پذیر است.")
        return
    if not UserRepo.get_by_telegram_id(user.id):
        UserRepo.upsert(user.id, user.username, user.first_name or "کاربر")
    code = (query.data or '').split(':', 1)[-1]
    plan = PlanRepo.get(code)
    if code not in PRODUCTS or not plan or not plan['is_active']:
        await _edit(query, "این محصول دیگر قابل خرید نیست؛ /plans را بزنید.")
        return
    order = PaymentService.create_order(user.id, code)
    if not order:
        pending = OrderRepo.get_open(user.id)
        if not pending:
            await _edit(query, "وضعیت سفارش تغییر کرده است؛ دوباره سرویس را انتخاب کنید.", reply_markup=back_to_main_keyboard())
            return
        order = pending[0]
    await _show_order(query, context, order, code)


async def orders_handler(update, context):
    query, user = update.callback_query, update.effective_user
    if query:
        await query.answer()
    if not await _account_allowed(update):
        return
    data = (query.data or '').split(':') if query else ['orders', 'list']
    if query and len(data) >= 3 and data[1] in ('view', 'switch'):
        order = OrderRepo.get_by_order_id(data[2])
        if not order or order['telegram_user_id'] != user.id:
            await _edit(query, "این سفارش در دسترس شما نیست.")
            return
        if data[1] == 'switch' and len(data) == 4 and data[3] in PRODUCTS:
            switched = OrderRepo.switch_unpaid(order['order_id'], user.id, data[3])
            if switched:
                order = switched
            else:
                order = OrderRepo.get_by_order_id(order['order_id'])
                await query.message.reply_text("سفارش تغییر نکرد؛ وضعیت آن عوض شده یا سفارش باز دیگری دارید. وضعیت فعلی را بررسی کنید.")
        await _show_order(query, context, order)
        return
    orders = OrderRepo.get_open(user.id)
    text = "🧾 <b>سفارش‌های باز شما</b>\n\n"
    rows = []
    if not orders:
        text += "سفارش باز ندارید؛ سرویس موردنظر را از بخش خرید انتخاب کنید."
    for order in orders[:10]:
        plan = PlanRepo.get(order['plan_code'])
        title = plan['title'] if plan else order['plan_code']
        status = 'در انتظار پرداخت' if order['status'] == 'awaiting_payment' else 'در انتظار بررسی رسید'
        text += f"• {escape(order['order_id'])} | {escape(title[:70])}\n{order['amount_toman']:,} تومان · {status}\n\n"
        rows.append([InlineKeyboardButton(f"🧾 {order['order_id']} · {status}", callback_data=f"orders:view:{order['order_id']}")])
    if len(orders) > 10:
        text += "۱۰ سفارش تازه‌تر نمایش داده شد؛ پس از تعیین وضعیت آن‌ها، بقیه قابل مشاهده‌اند."
    rows.append([InlineKeyboardButton("💳 انتخاب سرویس", callback_data="menu:plans")])
    keyboard = InlineKeyboardMarkup(rows)
    if query:
        await _edit(query, text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
