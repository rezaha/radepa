from __future__ import annotations
import os
from datetime import timedelta
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from app.config import config
from app.db.database import init_db
from app.db.repos import PlanRepo
from app.services.serper_service import SerperService
from app.services.job_service import JobService
from app.services.payment_service import PaymentService
from app.utils.logging_utils import setup_logging, get_logger

from app.handlers.start import (start_handler, main_menu_callback, help_handler, analyze_shortcut_handler, account_shortcut_handler, plans_shortcut_handler, reply_keyboard_router, channel_command)
from app.handlers.plans import show_plans_callback, buy_plan_callback
from app.handlers.payments import (receive_evidence_handler, admin_approve_callback,
    admin_reject_callback, admin_reject_note_handler, admin_order_detail_callback, cancel_order_callback)
from app.handlers.analysis import analyze_prompt_callback, receive_username_handler
from app.handlers.account import account_callback
from app.handlers.admin import (
    admin_command, stats_command, admin_callback, admin_text_handler,
)
from telegram.request import HTTPXRequest
from app.handlers.analysis import analyze_prompt_callback, receive_username_handler, result_view_callback
from app.handlers.support import support_prompt_callback, receive_support_message
from app.handlers.breach import breach_command, clear_pending_email, email_prompt_callback, receive_email
from app.services.leakcheck_public import LeakCheckPublic
from app.handlers.channel_stats import channel_stats_command
logger = get_logger(__name__)

def _seed_plans():
    from app.services.products import seed_products
    seed_products()
    logger.info("Plans seeded.")

async def _expire_orders_job(context):
    count = PaymentService.expire_old_orders()
    if count: logger.info("Expired %d orders.", count)

async def _on_error(update, context):
    # Never log update payloads, emails, API URLs or token-bearing exceptions.
    logger.error("Unhandled bot error: %s", type(context.error).__name__)

async def _on_shutdown(application):
    await application.bot_data["leakcheck_public"].close()

async def _route_text(update, context):
    if await reply_keyboard_router(update, context):
        return
    from app.config import config as cfg
    user = update.effective_user
    if not user: return
    ud = context.user_data
    if user.id in cfg.admin_ids:
        if await admin_text_handler(update, context):
            return
        if ud.get("rejecting_order_id"):
            from app.handlers.payments import admin_reject_note_handler
            await admin_reject_note_handler(update, context); return
        if ud.get("awaiting_support_message"):
            await receive_support_message(update, context);
            return
    if ud.get("awaiting_instagram_username"):
        await receive_username_handler(update, context); return
    from app.db.repos import OrderRepo
    if OrderRepo.get_latest_awaiting_payment(user.id):
        await receive_evidence_handler(update, context)

def main():
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    setup_logging(config.log_file, config.log_level)
    init_db(config.db_path)
    _seed_plans()
    from app.services.credit_service import CreditService
    CreditService.recover_interrupted()
    serper = SerperService()
    job_service = JobService(serper)
    # پروکسی فقط وقتی استفاده می‌شود که TELEGRAM_PROXY_URL در .env تنظیم شده باشد
    # (ویندوز/لوکال: TELEGRAM_PROXY_URL=socks5://127.0.0.1:10808 ـ سرور آلمان: خالی)
    proxy_url = os.environ.get("TELEGRAM_PROXY_URL", "").strip()
    builder = (Application.builder().token(config.bot_token)
               .post_shutdown(_on_shutdown))
    if proxy_url:
        try:
            builder = builder.request(HTTPXRequest(
                proxy=proxy_url,
                connect_timeout=30.0,
                read_timeout=30.0,
                write_timeout=30.0,
                connection_pool_size=8,
            ))
        except Exception as e:
            logger.warning("Proxy setup failed (%s); continuing without proxy.", e)
    app = builder.build()
    app.bot_data["bot_name"] = config.bot_name
    app.bot_data["job_service"] = job_service
    app.bot_data["leakcheck_public"] = LeakCheckPublic()
    app.add_error_handler(_on_error)
    app.job_queue.run_repeating(_expire_orders_job, interval=timedelta(hours=1), first=timedelta(minutes=5))

    app.add_handler(MessageHandler(filters.COMMAND, clear_pending_email), group=-2)
    app.add_handler(CallbackQueryHandler(clear_pending_email), group=-2)
    app.add_handler(CommandHandler("start",   start_handler))
    app.add_handler(CommandHandler("help",    help_handler))
    app.add_handler(CallbackQueryHandler(help_handler, pattern="^menu:help$"))
    app.add_handler(CommandHandler("analyze", analyze_shortcut_handler))
    app.add_handler(CommandHandler("account", account_shortcut_handler))
    app.add_handler(CommandHandler("plans",   plans_shortcut_handler))
    app.add_handler(CallbackQueryHandler(support_prompt_callback, pattern="^menu:support$"))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("channel", channel_command))
    app.add_handler(CommandHandler("channelstats", channel_stats_command))
    app.add_handler(CommandHandler("email", breach_command))
    app.add_handler(CommandHandler("verifyemail", breach_command))  # legacy alias; no email sent
    app.add_handler(CommandHandler("breach", breach_command))
    app.add_handler(CallbackQueryHandler(email_prompt_callback, pattern="^menu:email$"))
    app.add_handler(CallbackQueryHandler(result_view_callback, pattern=r"^result:"))
    app.add_handler(CallbackQueryHandler(main_menu_callback,              pattern="^menu:main$"))
    app.add_handler(CallbackQueryHandler(show_plans_callback,             pattern="^menu:plans$"))
    app.add_handler(CallbackQueryHandler(buy_plan_callback,               pattern=r"^buy:"))
    app.add_handler(CallbackQueryHandler(analyze_prompt_callback,         pattern="^menu:analyze$"))
    app.add_handler(CallbackQueryHandler(account_callback,                pattern="^menu:account$"))
    app.add_handler(CallbackQueryHandler(cancel_order_callback,           pattern=r"^cancel_order:"))
    app.add_handler(CallbackQueryHandler(admin_approve_callback,          pattern=r"^admin_approve:"))
    app.add_handler(CallbackQueryHandler(admin_reject_callback,           pattern=r"^admin_reject:"))
    app.add_handler(CallbackQueryHandler(admin_order_detail_callback,     pattern=r"^admin_order_detail:"))
    # ── پنل ادمین جدید ──
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm[_:]"))

    # Consume direct email lookups before Instagram/payment routing.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_text))
    app.add_handler(MessageHandler(filters.PHOTO, receive_evidence_handler))

    logger.info("Bot starting — polling mode")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
