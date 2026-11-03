"""User support intake and private, administrator-only replies."""
from __future__ import annotations

from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, Forbidden
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.config import config
from app.db.repos import UserRepo
from app.db.support_repo import SupportRepo
from app.utils.keyboards import back_to_main_keyboard, main_menu_keyboard
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)
ADMIN_ONLY = "این قابلیت فقط برای مدیر در گفت‌وگوی خصوصی فعال است."


def _private(update):
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


def _admin(update):
    return bool(update.effective_user and update.effective_user.id in config.admin_ids and _private(update))


async def support_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if not _private(update):
        await query.answer("پشتیبانی را در گفت‌وگوی خصوصی ربات باز کنید.", show_alert=True)
        return
    await query.answer()
    context.user_data["awaiting_support_message"] = True
    await query.edit_message_text(
        "📩 ارتباط با پشتیبانی\n\nپیام خود را بنویسید. پاسخ مدیر در همین ربات ارسال می‌شود.\n"
        "برای لغو، /start را بزنید.", parse_mode=None, reply_markup=back_to_main_keyboard(),
    )


async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_support_message"):
        return
    user, message = update.effective_user, update.effective_message
    if not user or not message or not message.text or not _private(update):
        return
    body = message.text.strip()
    if not body:
        return
    UserRepo.upsert(user.id, user.username, user.first_name or "کاربر")
    ticket_id = SupportRepo.create(user.id, message.message_id)
    username = f"@{user.username}" if user.username else "ندارد"
    header = (f"📩 پیام پشتیبانی جدید\n\n👤 کاربر: {(user.first_name or 'کاربر')[:128]}\n"
              f"نام کاربری: {username}\n🆔 شناسه: {user.id}\n\n💬 پیام:\n")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ پاسخ به کاربر", callback_data=f"support:reply:{ticket_id}")
    ]])
    delivered = False
    for admin_id in config.admin_ids:
        try:
            # At most 3000 UTF-16 units of body plus a bounded header per message.
            for offset in range(0, len(body), 1500):
                notification = await context.bot.send_message(
                    chat_id=admin_id, text=header + body[offset:offset + 1500],
                    parse_mode=None, reply_markup=keyboard,
                )
                SupportRepo.record_delivery(admin_id, notification.message_id, ticket_id)
            delivered = True
        except Exception as exc:
            logger.error("Support notification failed for admin=%d (%s)", admin_id, type(exc).__name__)
    if not delivered:
        await message.reply_text("ارسال کامل پیام به پشتیبانی انجام نشد؛ لطفاً بعداً دوباره تلاش کنید.")
        return
    context.user_data.pop("awaiting_support_message", None)
    await message.reply_text("✅ پیام شما به پشتیبانی ارسال شد. پاسخ در همین ربات می‌رسد.",
                             reply_markup=main_menu_keyboard())


async def support_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if not _admin(update):
        await query.answer(ADMIN_ONLY, show_alert=True)
        return
    ticket = SupportRepo.get((query.data or "").removeprefix("support:reply:"))
    if not ticket:
        await query.answer("این درخواست موجود نیست یا کاربر حذف شده است.", show_alert=True)
        return
    await query.answer()
    prompt = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"↩️ پاسخ به کاربر {ticket['telegram_user_id']}\n"
             "روی همین پیام Reply کنید و پاسخ را بفرستید. برای انصراف، از حالت Reply خارج شوید.",
        parse_mode=None, reply_markup=ForceReply(input_field_placeholder="پاسخ پشتیبانی"),
    )
    SupportRepo.record_delivery(update.effective_chat.id, prompt.message_id, ticket['id'])


async def receive_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not _admin(update):
        return False
    message = update.effective_message
    quoted = getattr(message, "reply_to_message", None)
    if quoted is None:
        return False
    ticket = SupportRepo.for_reply(update.effective_chat.id, quoted.message_id)
    if not ticket:
        # Old notifications have no DB link. Never guess an ID from their text:
        # the original user's name/body could contain a forged ID line.
        author = getattr(quoted, "from_user", None)
        if (author and author.id == context.bot.id
                and (getattr(quoted, "text", None) or "").startswith("📩 پیام پشتیبانی جدید")):
            await message.reply_text(
                "این پیام قدیمی لینک پاسخ ثبت‌شده ندارد. گیرنده را بررسی کنید و بنویسید:\n"
                "/reply USER_ID متن پاسخ", parse_mode=None,
            )
            return True
        return False
    try:
        # copy_message keeps entities/media, without forwarding the admin identity.
        await context.bot.copy_message(chat_id=ticket['telegram_user_id'],
                                       from_chat_id=update.effective_chat.id,
                                       message_id=message.message_id)
    except Forbidden:
        await message.reply_text("پاسخ ارسال نشد؛ دسترسی ربات به گفت‌وگوی کاربر مسدود یا غیرفعال است.")
    except TelegramError as exc:
        logger.warning("Support reply failed (%s)", type(exc).__name__)
        await message.reply_text("پاسخ ارسال نشد یا تحویل آن تأیید نشد؛ وضعیت را بررسی و در صورت نیاز دوباره تلاش کنید.")
    else:
        await message.reply_text(f"✅ پاسخ به کاربر {ticket['telegram_user_id']} ارسال شد.")
    return True


async def support_reply_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await receive_admin_reply(update, context):
        # A support reply must never become an email lookup or payment evidence.
        raise ApplicationHandlerStop


async def support_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    if not _admin(update):
        await message.reply_text(ADMIN_ONLY)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[2].strip():
        await message.reply_text("روش استفاده:\n/reply USER_ID متن پاسخ\n/reply @username متن پاسخ", parse_mode=None)
        return
    identifier, body = parts[1], parts[2]
    if identifier.isascii() and identifier.isdigit() and 0 < len(identifier) <= 18:
        target = UserRepo.get_by_telegram_id(int(identifier))
    elif identifier.startswith('@') and 1 < len(identifier) <= 33:
        matches = SupportRepo.username_matches(identifier[1:])
        target = matches[0] if len(matches) == 1 else None
        if target:
            try:
                current = await context.bot.get_chat(target['telegram_user_id'])
            except TelegramError:
                await message.reply_text("نام کاربری فعلی قابل تأیید نیست؛ از شناسه عددی کاربر استفاده کنید.")
                return
            if not current.username or current.username.lower() != identifier[1:].lower():
                await message.reply_text("نام کاربری ذخیره‌شده تغییر کرده است؛ گیرنده را بررسی و از شناسه عددی استفاده کنید.")
                return
    else:
        target = None
    if not target:
        await message.reply_text("کاربر شناخته‌شده و یکتایی پیدا نشد؛ شناسه عددی یا username دقیق را بررسی کنید.")
        return
    try:
        await context.bot.send_message(chat_id=target['telegram_user_id'], text=body, parse_mode=None)
    except Forbidden:
        await message.reply_text("پاسخ ارسال نشد؛ دسترسی ربات به گفت‌وگوی کاربر مسدود یا غیرفعال است.")
    except TelegramError as exc:
        logger.warning("Support command delivery failed (%s)", type(exc).__name__)
        await message.reply_text("پاسخ ارسال نشد یا تحویل آن تأیید نشد؛ وضعیت را بررسی کنید.")
    else:
        await message.reply_text(f"✅ پاسخ به کاربر {target['telegram_user_id']} ارسال شد.")
