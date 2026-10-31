from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from app.config import config
from app.db.repos import OrderRepo, PlanRepo, UserRepo
from app.services.payment_service import PaymentService
from app.services.receipt_review import send_order_review, edit_review
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
    for admin_id in config.admin_ids:
        try:
            await send_order_review(context.bot, admin_id, order)
        except Exception as exc:
            logger.error("Receipt notification failed for admin %d (%s)", admin_id, type(exc).__name__)

async def receive_evidence_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    selected = context.user_data.get("pending_order_id")
    order = OrderRepo.get_by_order_id(selected) if selected else OrderRepo.get_latest_awaiting_payment(user.id)
    if not order: return
    if order['telegram_user_id'] != user.id or order['status'] != 'awaiting_payment':
        await update.effective_message.reply_text("این سفارش دیگر پذیرای رسید نیست؛ با /orders وضعیت سفارش را بررسی کنید.")
        return
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
    document = getattr(update.message, 'document', None) if update.message else None
    if document and (document.mime_type or '').startswith('image/'):
        if not PaymentService.submit_document_evidence(order_id, document.file_id):
            await update.message.reply_text(GENERIC_ERROR)
            return
        await update.message.reply_text(EVIDENCE_RECEIVED.format(order_id=order_id),
            parse_mode="Markdown", reply_markup=back_to_main_keyboard())
        updated = OrderRepo.get_by_order_id(order_id)
        if updated:
            await _notify_admins(context, updated)
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
        await edit_review(query, ORDER_ALREADY_PROCESSED); return
    try:
        await context.bot.send_message(
            chat_id=result["user_telegram_id"],
            text=(f"✅ پرداخت سفارش {order_id} تأیید شد.\n"
                  f"سرویس: {result['service_title']}\nاعتبار افزوده‌شده: {result['credits']} جست‌وجو\n"
                  + (f"انقضا: {format_shamsi_approx(result['expire_iso'])}" if result['expire_iso']
                     else "بدون انقضای زمانی؛ از منو سرویس خریداری‌شده را انتخاب کنید.")),
            parse_mode=None, reply_markup=back_to_main_keyboard())
    except Exception as exc:
        logger.error("Failed to notify user: %s", exc)
    await edit_review(query, f"✅ سفارش `{order_id}` تأیید شد.", parse_mode="Markdown")

async def admin_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await query.answer(ADMIN_ONLY, show_alert=True); return
    await query.answer()
    order_id = (query.data or "").split(":", 1)[-1]
    context.user_data["rejecting_order_id"] = order_id
    await edit_review(query,
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
        await edit_review(query, ORDER_NOT_FOUND); return
    await send_order_review(context.bot, user.id, order)


async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    user = update.effective_user
    if not user: return
    order_id = (query.data or "").split(":", 1)[-1]
    order = OrderRepo.get_by_order_id(order_id)
    if not order or order["telegram_user_id"] != user.id:
        await edit_review(query, ORDER_NOT_FOUND); return
    if order["status"] != "awaiting_payment":
        await edit_review(query, ORDER_ALREADY_PROCESSED, reply_markup=back_to_main_keyboard()); return
    from app.db.database import get_connection
    with get_connection() as conn:
        changed = conn.execute("UPDATE orders SET status='expired',updated_at=? WHERE order_id=? AND telegram_user_id=? AND status='awaiting_payment'",
            (now_iso(), order_id, user.id)).rowcount
        conn.commit()
    if not changed:
        await edit_review(query, ORDER_ALREADY_PROCESSED, reply_markup=back_to_main_keyboard())
        return
    await edit_review(query, f"سفارش `{order_id}` لغو شد.",
        parse_mode="Markdown", reply_markup=back_to_main_keyboard())
