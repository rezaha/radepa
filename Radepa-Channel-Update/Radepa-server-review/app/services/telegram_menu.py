"""Native Telegram command menu. Only existing, authorized handlers are listed."""
from __future__ import annotations

import asyncio
from telegram import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, MenuButtonCommands
from telegram.error import TelegramError

from app.config import config
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)
LANGUAGES = ('', 'fa')
PUBLIC_COMMANDS = (
    BotCommand('start', '🏠 شروع و نمایش منوی اصلی'),
    BotCommand('account', '👤 حساب من و موجودی اعتبار'),
    BotCommand('plans', '💳 خرید جست‌وجو'),
    BotCommand('orders', '🧾 سفارش‌ها و پیگیری پرداخت'),
    BotCommand('email', '📧 بررسی نشت یک ایمیل'),
    BotCommand('analyze', '🔎 تحلیل ردپای عمومی اینستاگرام'),
    BotCommand('help', '📖 راهنمای استفاده'),
    BotCommand('channel', '📢 کانال اطلاع‌رسانی'),
    BotCommand('cancel', '↩️ لغو ورودی و بازگشت به منو'),
)
ADMIN_COMMANDS = PUBLIC_COMMANDS + (
    BotCommand('admin', '⚙️ پنل مدیریت'),
    BotCommand('stats', '📊 آمار ربات'),
    BotCommand('reply', '↩️ پاسخ پشتیبانی با ID یا username'),
    BotCommand('instagram', '🔍 وضعیت دسترسی صفحه اینستاگرام'),
    BotCommand('channelstats', '📊 مدیریت پیام آمار کانال'),
)


async def _commands(bot, commands, scope):
    for language in LANGUAGES:
        if await bot.set_my_commands(commands, scope=scope, language_code=language) is not True:
            raise TelegramError('Command menu was not confirmed')


async def _chat_menu(bot, chat_id, is_admin):
    await _commands(bot, ADMIN_COMMANDS if is_admin else PUBLIC_COMMANDS,
                    BotCommandScopeChat(chat_id))
    if await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands()) is not True:
        raise TelegramError('Chat menu button was not confirmed')


async def ensure_private_menu(bot, bot_data, chat_id: int, is_admin: bool) -> bool:
    cache = bot_data.setdefault('telegram_menu_chats', {})
    if cache.get(chat_id) is is_admin:
        return True
    try:
        await asyncio.wait_for(_chat_menu(bot, chat_id, is_admin), timeout=5)
    except (TelegramError, asyncio.TimeoutError) as exc:
        # Missing menu settings must not stop /start, billing or support.
        logger.warning('Telegram chat menu setup failed for chat=%d (%s)', chat_id, type(exc).__name__)
        return False
    cache[chat_id] = is_admin
    return True


async def _configure(application):
    try:
        await _commands(application.bot, PUBLIC_COMMANDS, BotCommandScopeAllPrivateChats())
        if await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands()) is not True:
            raise TelegramError('Default menu button was not confirmed')
    except TelegramError as exc:
        logger.warning('Telegram default menu setup failed (%s)', type(exc).__name__)
    for admin_id in dict.fromkeys(config.admin_ids):
        await ensure_private_menu(application.bot, application.bot_data, admin_id, True)


async def configure_application_menu(application) -> None:
    """post_init runs after Telegram initialization, before polling starts."""
    try:
        await asyncio.wait_for(_configure(application), timeout=20)
    except (TelegramError, asyncio.TimeoutError) as exc:
        logger.warning('Telegram menu initialization incomplete (%s)', type(exc).__name__)
