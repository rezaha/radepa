from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from app.config import config
from app.db.repos import OrderRepo, PlanRepo, UserRepo
from app.services.payment_service import PaymentService
from app.utils.texts_fa import (EVIDENCE_RECEIVED, PAYMENT_APPROVED, PAYMENT_REJECTED,
    ORDER_NOT_FOUND, ORDER_ALREADY_PROCESSED, ADMIN_NEW_EVIDENCE, ADMIN_ONLY,
    GENERIC_ERROR, ADMIN_ORDER_DETAIL)
from app.utils.keyboards import admin_review_keyboard, back_to_main_keyboard
from app.utils.time_utils import format_shamsi_approx, now_iso
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

def _is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids

async def _notify_admins(context, order: dict) -> None:
    user = UserRepo.get_by_telegram_id(order["telegram_user_id"])
    plan = PlanRepo.get(order["plan_code"])
    plan_title = plan["title"] if plan else order["plan_code"]
    evidence_line = ""
    if order["evidence_type"] == "text":
        evidence_line = f"شناسه تراکنش: `{order['evidence_text']}`"
    elif order["evidence_type"] == "photo":
        evidence_line = "📸 عکس رسید ارسال شده"
    text = ADMIN_NEW_EVIDENCE.format(
        order_id=order["order_id"],
        first_name=user["first_name"] if user else "?",
        username=(user["username"] or "بدون یوزرنیم") if user else "?",
        amount=order["amount_toman"], plan_title=plan_title,
        evidence_type=order["evidence_type"], evidence_line=evidence_line)
    keyboard = admin_review_keyboard(order["order_id"])
    for admin_id in config.admin_ids:
        try:
            if order["evidence_type"] == "photo" and order.get("evidence_file_id"):
                await context.bot.send_photo(chat_id=admin_id, photo=order["evidence_file_id"],
                    caption=text, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await context.bot.send_message(chat_id=admin_id, text=text,
                    parse_mode="Markdown", reply_markup=keyboard)
        except Exception as exc:
            logger.error("Failed to notify admin %d: %s", admin_id, exc)

async def receive_evidence_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    order = OrderRepo.get_latest_awaiting_payment(user.id)
    if not order: return
    order_id = order["order_id"]
    if update.message and update.message.photo:
        file_id = update.message.photo[-1].file_id
        if not PaymentService.submit_photo_evidence(order_id, file_id):
            await update.message.reply_text(GENERIC_ERROR)
            return
        await update.message.reply_text(EVIDENCE_RECEIVED.format(order_id=order_id),
            parse_mode="Markdown", reply_markup=back_to_main_keyboard())
        updated = OrderRepo.get_by_order_id(order_id)
        if updated: await _notify_admins(context, updated)
        return
    if update.message and update.message.text:
        text_ev = update.message.text.strip()
        if len(text_ev) >= 6 and not text_ev.startswith("/"):
            if not PaymentService.submit_text_evidence(order_id, text_ev):
                await update.message.reply_text(GENERIC_ERROR)
                return
            await update.message.reply_text(EVIDENCE_RECEIVED.format(order_id=order_id),
                parse_mode="Markdown", reply_markup=back_to_main_keyboard())
            updated = OrderRepo.get_by_order_id(order_id)
            if updated: await _notify_admins(context, updated)

async def admin_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await query.answer(ADMIN_ONLY, show_alert=True); return
    await query.answer()
    order_id = (query.data or "").split(":", 1)[-1]
    result = PaymentService.approve_order(order_id, user.id)
    if not result:
        await query.edit_message_text(ORDER_ALREADY_PROCESSED); return
    try:
        await context.bot.send_message(
            chat_id=result["user_telegram_id"],
            text=PAYMENT_APPROVED.format(order_id=order_id, credits=result["credits"],
                expire=format_shamsi_approx(result["expire_iso"])),
            parse_mode="Markdown", reply_markup=back_to_main_keyboard())
    except Exception as exc:
        logger.error("Failed to notify user: %s", exc)
    await query.edit_message_text(f"✅ سفارش `{order_id}` تأیید شد.", parse_mode="Markdown")

async def admin_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await query.answer(ADMIN_ONLY, show_alert=True); return
    await query.answer()
    order_id = (query.data or "").split(":", 1)[-1]
    context.user_data["rejecting_order_id"] = order_id
    await query.edit_message_text(
        f"دلیل رد سفارش `{order_id}` رو بنویس:\n_(برای رد بدون دلیل: /skip)_",
        parse_mode="Markdown")

async def admin_reject_note_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not _is_admin(user.id): return
    order_id = context.user_data.get("rejecting_order_id")
    if not order_id or not update.message or not update.message.text: return
    del context.user_data["rejecting_order_id"]
    note = "توضیحی ارائه نشده." if update.message.text.strip() == "/skip" else update.message.text.strip()
    result = PaymentService.reject_order(order_id, user.id, note)
    if not result:
        await update.message.reply_text(ORDER_ALREADY_PROCESSED); return
    try:
        await context.bot.send_message(
            chat_id=result["user_telegram_id"],
            text=PAYMENT_REJECTED.format(order_id=order_id, note=note),
            parse_mode="Markdown", reply_markup=back_to_main_keyboard())
    except Exception as exc:
        logger.error("Failed to notify user: %s", exc)
    await update.message.reply_text(f"❌ سفارش `{order_id}` رد شد.", parse_mode="Markdown")

async def admin_order_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await query.answer(ADMIN_ONLY, show_alert=True); return
    await query.answer()
    order_id = (query.data or "").split(":", 1)[-1]
    order = OrderRepo.get_by_order_id(order_id)
    if not order:
        await query.edit_message_text(ORDER_NOT_FOUND); return
    db_user = UserRepo.get_by_telegram_id(order["telegram_user_id"])
    await query.edit_message_text(ADMIN_ORDER_DETAIL.format(
        order_id=order["order_id"],
        first_name=db_user["first_name"] if db_user else "?",
        username=(db_user["username"] or "—") if db_user else "—",
        plan_code=order["plan_code"], amount=order["amount_toman"],
        status=order["status"], created_at=order["created_at"],
        evidence_type=order["evidence_type"]), parse_mode="Markdown")

async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    user = update.effective_user
    if not user: return
    order_id = (query.data or "").split(":", 1)[-1]
    order = OrderRepo.get_by_order_id(order_id)
    if not order or order["telegram_user_id"] != user.id:
        await query.edit_message_text(ORDER_NOT_FOUND); return
    if order["status"] != "awaiting_payment":
        await query.edit_message_text(ORDER_ALREADY_PROCESSED, reply_markup=back_to_main_keyboard()); return
    from app.db.database import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE orders SET status='expired',updated_at=? WHERE order_id=? AND telegram_user_id=?",
            (now_iso(), order_id, user.id))
        conn.commit()
    await query.edit_message_text(f"سفارش `{order_id}` لغو شد.",
        parse_mode="Markdown", reply_markup=back_to_main_keyboard())
