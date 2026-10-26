from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from app.db.repos import PlanRepo, UserRepo
from app.services.payment_service import PaymentService
from app.utils.texts_fa import PLANS_HEADER, PLAN_ITEM, NO_ACTIVE_PLANS, PAYMENT_INSTRUCTIONS, GENERIC_ERROR
from app.utils.keyboards import plan_buy_keyboard, cancel_order_keyboard, back_to_main_keyboard
from app.config import config
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

async def show_plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    if update.effective_user: UserRepo.touch(update.effective_user.id)
    plans = PlanRepo.get_active()
    if not plans:
        await query.edit_message_text(NO_ACTIVE_PLANS, reply_markup=back_to_main_keyboard())
        return
    plan = plans[0]
    text = PLANS_HEADER + PLAN_ITEM.format(
        title=plan["title"], price=plan["price_toman"],
        credits=plan["credits"], duration=plan["duration_days"])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=plan_buy_keyboard(plan["plan_code"]))

async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    user = update.effective_user
    if not user: return
    plan_code = (query.data or "").split(":", 1)[-1]
    plan = PlanRepo.get(plan_code)
    if not plan:
        await query.edit_message_text(GENERIC_ERROR, reply_markup=back_to_main_keyboard())
        return
    order = PaymentService.create_order(user.id, plan_code)
    if not order:
        await query.edit_message_text(GENERIC_ERROR, reply_markup=back_to_main_keyboard())
        return
    context.user_data["pending_order_id"] = order["order_id"]
    await query.edit_message_text(
        PAYMENT_INSTRUCTIONS.format(
            card_number=config.payment_card_number, card_holder=config.payment_card_holder,
            amount=order["amount_toman"], order_id=order["order_id"]),
        parse_mode="Markdown", reply_markup=cancel_order_keyboard(order["order_id"]))



async def _send_plans(message, context):
    """قابل فراخوانی هم از callback و هم از message مستقیم."""
    from app.db.repos import PlanRepo
    plans = PlanRepo.get_active()
    if not plans:
        await message.reply_text("در حال حاضر پلنی موجود نیست.")
        return
    from app.utils.keyboards import plan_buy_keyboard
    for plan in plans:
        text = (
            f"📦 *{plan['title']}*\n\n"
            f"💰 قیمت: {plan['price_toman']:,} تومان\n"
            f"💎 اعتبار: {plan['credits']} تحلیل\n"
            f"📅 مدت: {plan['duration_days']} روز"
        )
        await message.reply_text(text, parse_mode="Markdown",
                                  reply_markup=plan_buy_keyboard(plan["plan_code"]))
