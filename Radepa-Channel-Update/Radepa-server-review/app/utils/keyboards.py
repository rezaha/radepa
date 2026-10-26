from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

INSTAGRAM_BUTTON = "🔎 تحلیل اینستاگرام"
ORDERS_BUTTON = "🧾 سفارش‌های من"

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 بررسی ایمیل", callback_data="menu:email"),
         InlineKeyboardButton(INSTAGRAM_BUTTON, callback_data="menu:analyze")],
        [InlineKeyboardButton("💳 خرید جست‌وجو", callback_data="menu:plans"),
         InlineKeyboardButton(ORDERS_BUTTON, callback_data="orders:list")],
        [InlineKeyboardButton("👤 حساب من", callback_data="menu:account"),
         InlineKeyboardButton("📖 راهنمای استفاده", callback_data="menu:help")],
        [InlineKeyboardButton("📩 پشتیبانی", callback_data="menu:support")],
        [InlineKeyboardButton("📢 کانال اطلاع‌رسانی", url="https://t.me/Radepa_Updates")],
    ])

def plan_buy_keyboard(plan_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید این پلن", callback_data=f"buy:{plan_code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu:main")],
    ])

def cancel_order_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order:{order_id}")],
    ])

def admin_review_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"admin_approve:{order_id}"),
         InlineKeyboardButton("❌ رد پرداخت", callback_data=f"admin_reject:{order_id}")],
        [InlineKeyboardButton("🧾 جزئیات سفارش", callback_data=f"admin_order_detail:{order_id}")],
    ])

def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار", callback_data="admin:stats"),
         InlineKeyboardButton("📋 سفارشات", callback_data="admin:pending_orders")],
        [InlineKeyboardButton("👤 جستجوی کاربر", callback_data="admin:user_search"),
         InlineKeyboardButton("📤 خروجی آمار", callback_data="admin:export")],
    ])

def admin_user_actions_keyboard(telegram_user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    block_label = "✅ رفع مسدودیت" if is_blocked else "🚫 مسدود کردن"
    block_data = f"admin_unblock:{telegram_user_id}" if is_blocked else f"admin_block:{telegram_user_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ تمدید اشتراک", callback_data=f"admin_extend:{telegram_user_id}"),
         InlineKeyboardButton(block_label, callback_data=block_data)],
    ])

def account_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 خرید جست‌وجو", callback_data="menu:plans")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu:main")],
    ])

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu:main")],
    ])
