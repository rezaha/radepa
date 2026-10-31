# === app/handlers/admin.py ===
from __future__ import annotations
import functools
from datetime import timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.config import config
from app.db.repos import UserRepo, OrderRepo, JobRepo
from app.utils.time_utils import now_utc, format_shamsi_approx
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)


# ─── patch repos ──────────────────────────────────────────────
def _ensure_patched():
    if not hasattr(UserRepo, "list_recent"):
        _apply_patches()

def _apply_patches():
    from app.db.repos import get_connection, _rows
    from datetime import timedelta

    @staticmethod
    def _user_list_recent(limit: int = 30):
        with get_connection() as conn:
            return _rows(conn.execute(
                "SELECT * FROM users ORDER BY last_seen_at DESC LIMIT ?", (limit,)
            ).fetchall())

    @staticmethod
    def _user_search(query: str):
        with get_connection() as conn:
            return _rows(conn.execute(
                "SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ?"
                " ORDER BY last_seen_at DESC LIMIT 20",
                (f"%{query}%", f"%{query}%"),
            ).fetchall())

    @staticmethod
    def _user_list_blocked():
        with get_connection() as conn:
            return _rows(conn.execute(
                "SELECT * FROM users WHERE is_blocked=1 ORDER BY last_seen_at DESC"
            ).fetchall())

    @staticmethod
    def _count_online(minutes: int = 5):
        from app.utils.time_utils import now_utc as _now
        cutoff = (_now() - timedelta(minutes=minutes)).isoformat()
        with get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE last_seen_at >= ? AND is_blocked=0",
                (cutoff,)
            ).fetchone()[0]

    @staticmethod
    def _delete_user(telegram_user_id: int) -> bool:
        # Explicit admin-only action. Keep the order/job/source deletion in one
        # SQLite transaction so a partial deletion cannot be committed.
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM job_sources WHERE job_id IN "
                "(SELECT id FROM jobs WHERE telegram_user_id=?)", (telegram_user_id,))
            conn.execute("DELETE FROM jobs WHERE telegram_user_id=?", (telegram_user_id,))
            conn.execute("DELETE FROM orders WHERE telegram_user_id=?", (telegram_user_id,))
            cur = conn.execute("DELETE FROM users WHERE telegram_user_id=?", (telegram_user_id,))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _revenue_total():
        with get_connection() as conn:
            r = conn.execute(
                "SELECT SUM(amount_toman) FROM orders WHERE status='paid'"
            ).fetchone()
            return r[0] or 0

    @staticmethod
    def _count_today_paid():
        from app.utils.time_utils import now_utc as _now
        today = _now().strftime("%Y-%m-%d")
        with get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status='paid' AND created_at LIKE ?",
                (f"{today}%",)
            ).fetchone()[0]

    @staticmethod
    def _job_list_by_user(tid: int, limit: int = 10):
        with get_connection() as conn:
            return _rows(conn.execute(
                "SELECT * FROM jobs WHERE telegram_user_id=? ORDER BY created_at DESC LIMIT ?",
                (tid, limit),
            ).fetchall())

    @staticmethod
    def _job_count_today():
        from app.utils.time_utils import now_utc as _now
        today = _now().strftime("%Y-%m-%d")
        with get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE created_at LIKE ?", (f"{today}%",)
            ).fetchone()[0]

    @staticmethod
    def _order_list_all(limit: int = 50):
        with get_connection() as conn:
            return _rows(conn.execute(
                """SELECT o.*, u.first_name, u.username FROM orders o
                   LEFT JOIN users u ON o.telegram_user_id=u.telegram_user_id
                   ORDER BY o.created_at DESC LIMIT ?""", (limit,)
            ).fetchall())

    UserRepo.list_recent      = _user_list_recent
    UserRepo.search_by_username = _user_search
    UserRepo.list_blocked     = _user_list_blocked
    UserRepo.count_online     = _count_online
    UserRepo.delete_user      = _delete_user
    OrderRepo.revenue_total   = _revenue_total
    OrderRepo.count_today_paid = _count_today_paid
    OrderRepo.list_all        = _order_list_all
    JobRepo.list_by_user      = _job_list_by_user
    JobRepo.count_today       = _job_count_today


# ─── کمک‌کننده‌ها ─────────────────────────────────────────────
def _is_admin(uid: int) -> bool:
    return uid in config.admin_ids


def admin_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not _is_admin(user.id):
            if update.message:
                await update.message.reply_text("⛔ فقط ادمین می‌تونه این کار رو بکنه.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        _ensure_patched()
        return await func(update, context)
    return wrapper


# ─── کیبوردها ─────────────────────────────────────────────────
def _admin_main_menu(total: int = 0, online: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📊 آمار  |  👥 {total} کاربر  |  🟢 {online} آنلاین",
            callback_data="adm:stats"
        )],
        [InlineKeyboardButton("👥 مدیریت کاربران",    callback_data="adm:users_menu"),
         InlineKeyboardButton("🛒 سفارشات در انتظار", callback_data="adm:pending")],
        [InlineKeyboardButton("📋 همه سفارشات",       callback_data="adm:all_orders"),
         InlineKeyboardButton("📤 خروجی گزارش",       callback_data="adm:export")],
        [InlineKeyboardButton("📢 پیام همگانی",       callback_data="adm:broadcast")],
    ])


def _admin_users_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 آخرین کاربران",  callback_data="adm:recent_users"),
         InlineKeyboardButton("🟢 کاربران آنلاین", callback_data="adm:online_users")],
        [InlineKeyboardButton("🔍 جستجو با نام",   callback_data="adm:search_user"),
         InlineKeyboardButton("🔢 جستجو با آیدی",  callback_data="adm:id_search")],
        [InlineKeyboardButton("🚫 کاربران مسدود",  callback_data="adm:blocked_users")],
        [InlineKeyboardButton("◀️ برگشت",           callback_data="adm:main")],
    ])


def _admin_user_actions(tid: int, is_blocked: bool) -> InlineKeyboardMarkup:
    block_text = "✅ رفع مسدودیت" if is_blocked else "🚫 مسدودکردن"
    block_cb   = f"adm_unblock:{tid}" if is_blocked else f"adm_block:{tid}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن روز",        callback_data=f"adm_adddays:{tid}"),
         InlineKeyboardButton("💎 افزودن اعتبار",    callback_data=f"adm_addcredits:{tid}")],
        [InlineKeyboardButton("🎁 اشتراک رایگان",    callback_data=f"adm_free_plan:{tid}"),
         InlineKeyboardButton("📋 سفارشات",          callback_data=f"adm_orders:{tid}")],
        [InlineKeyboardButton("🔍 تحلیل‌های او",     callback_data=f"adm_jobs:{tid}"),
         InlineKeyboardButton(block_text,             callback_data=block_cb)],
        [InlineKeyboardButton("🗑 حذف کامل کاربر",   callback_data=f"adm_delete:{tid}")],
        [InlineKeyboardButton("◀️ برگشت",             callback_data="adm:users_menu")],
    ])


def _admin_review_kb(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"adm_approve:{order_id}"),
         InlineKeyboardButton("❌ رد پرداخت",   callback_data=f"adm_reject:{order_id}")],
        [InlineKeyboardButton("🧾 جزئیات",      callback_data=f"adm_odetail:{order_id}")],
    ])


def _confirm_delete_kb(tid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ بله، حذف کامل", callback_data=f"adm_delete_confirm:{tid}"),
         InlineKeyboardButton("❌ لغو", callback_data="adm:users_menu")],
    ])


def _back(cb: str = "adm:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ برگشت", callback_data=cb)]])


# ─── فرمت‌کننده‌ها ────────────────────────────────────────────
def _fmt_user(u: dict) -> str:
    blocked = "🚫 مسدود" if u.get("is_blocked") else "✅ فعال"
    exp     = format_shamsi_approx(u.get("subscription_expire_at"))
    ls      = format_shamsi_approx(u.get("last_seen_at"))
    uname   = f"@{u['username']}" if u.get("username") else "—"
    return (
        f"👤 *{u.get('first_name','؟')}* ({uname})\n"
        f"🆔 `{u['telegram_user_id']}`\n"
        f"📧 ایمیل: {u.get('email_credits',0)} | 🔎 اینستاگرام: {u.get('instagram_credits',0)}\n"
        f"💎 اعتبار قدیمی اینستاگرام: {u.get('credits',0)} | انقضا: {exp}\n"
        f"وضعیت: {blocked} | آخرین بازدید: {ls}"
    )


def _fmt_order(o: dict) -> str:
    status_map = {
        "awaiting_payment": "⏳ در انتظار پرداخت",
        "awaiting_review":  "🔍 در انتظار بررسی",
        "paid":             "✅ تأییدشده",
        "rejected":         "❌ ردشده",
        "expired":          "⌛ منقضی",
    }
    return (
        f"🧾 `{o['order_id']}`\n"
        f"👤 {o.get('first_name','؟')} | 💰 {o.get('amount_toman',0):,} ت\n"
        f"📌 {status_map.get(o.get('status','?'), o.get('status','?'))}\n"
        f"🕐 {o.get('created_at','')[:16]}"
    )


# ════════════════════════════════════════════════════════════════
#  /admin  و  /stats
# ════════════════════════════════════════════════════════════════
@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_patched()
    total  = UserRepo.count_total()
    online = UserRepo.count_online(5) if hasattr(UserRepo, "count_online") else 0
    await update.message.reply_text(
        f"⚙️ *پنل مدیریت ردپاگرد*\n"
        f"👥 کل کاربران: *{total}* | 🟢 آنلاین: *{online}*\n\n"
        f"چی می‌خوای ببینی؟",
        parse_mode="Markdown",
        reply_markup=_admin_main_menu(total, online),
    )


@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_stats_msg(update, context)


# ════════════════════════════════════════════════════════════════
#  Callback dispatcher مرکزی
# ════════════════════════════════════════════════════════════════
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not update.effective_user or not _is_admin(update.effective_user.id):
        if q: await q.answer("⛔ دسترسی ندارید.", show_alert=True)
        return
    _ensure_patched()
    await q.answer()
    data = q.data or ""

    if data == "adm:main":
        total  = UserRepo.count_total()
        online = UserRepo.count_online(5) if hasattr(UserRepo, "count_online") else 0
        await q.edit_message_text(
            f"⚙️ *پنل مدیریت ردپاگرد*\n"
            f"👥 کل کاربران: *{total}* | 🟢 آنلاین: *{online}*\n\nچی می‌خوای ببینی؟",
            parse_mode="Markdown",
            reply_markup=_admin_main_menu(total, online),
        )

    elif data == "adm:stats":
        await _send_stats_msg(update, context)

    elif data == "adm:export":
        await _export_report(update, context)

    elif data == "adm:users_menu":
        total  = UserRepo.count_total()
        online = UserRepo.count_online(5) if hasattr(UserRepo, "count_online") else 0
        await q.edit_message_text(
            f"👥 *مدیریت کاربران*\n"
            f"کل: *{total}* | آنلاین: *{online}*\n\nیکی رو انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=_admin_users_menu(),
        )

    elif data == "adm:recent_users":
        await _list_recent_users(update, context)

    elif data == "adm:online_users":
        await _list_online_users(update, context)

    elif data == "adm:blocked_users":
        await _list_blocked_users(update, context)

    elif data == "adm:search_user":
        context.user_data["adm_await"] = "search_username"
        await q.edit_message_text(
            "🔍 نام یا username کاربر رو بنویس:",
            reply_markup=_back("adm:users_menu")
        )

    elif data == "adm:id_search":
        context.user_data["adm_await"] = "search_id"
        await q.edit_message_text(
            "🔢 آیدی عددی تلگرام کاربر رو بفرست:",
            reply_markup=_back("adm:users_menu")
        )

    elif data == "adm:pending":
        await _show_pending_orders(update, context)

    elif data == "adm:all_orders":
        await _show_all_orders(update, context)

    elif data == "adm:broadcast":
        context.user_data["adm_await"] = "broadcast"
        await q.edit_message_text(
            "📢 متن پیام همگانی رو بنویس:\n(برای لغو /cancel بزن)",
            reply_markup=_back("adm:main")
        )

    elif data.startswith("adm_block:"):
        tid = int(data.split(":", 1)[1])
        UserRepo.set_blocked(tid, True)
        await q.edit_message_text(
            f"🚫 کاربر `{tid}` مسدود شد.",
            parse_mode="Markdown",
            reply_markup=_back("adm:users_menu")
        )

    elif data.startswith("adm_unblock:"):
        tid = int(data.split(":", 1)[1])
        UserRepo.set_blocked(tid, False)
        await q.edit_message_text(
            f"✅ مسدودیت کاربر `{tid}` برداشته شد.",
            parse_mode="Markdown",
            reply_markup=_back("adm:users_menu")
        )

    elif data.startswith("adm_delete:"):
        tid = int(data.split(":", 1)[1])
        u = UserRepo.get_by_telegram_id(tid)
        if not u:
            await q.edit_message_text("کاربر پیدا نشد.", reply_markup=_back("adm:users_menu"))
            return
        await q.edit_message_text(
            f"⚠️ حذف کامل کاربر `{tid}`؟\n"
            "سفارش‌ها، سوابق پرداخت ثبت‌شده و تحلیل‌های او نیز پاک می‌شوند. "
            "این کار برگشت‌ناپذیر است.",
            parse_mode="Markdown",
            reply_markup=_confirm_delete_kb(tid),
        )

    elif data.startswith("adm_delete_confirm:"):
        tid = int(data.split(":", 1)[1])
        deleted = UserRepo.delete_user(tid)
        await q.edit_message_text(
            (f"🗑 کاربر `{tid}` و داده‌های وابسته حذف شد." if deleted
             else f"کاربر `{tid}` پیدا نشد."),
            parse_mode="Markdown",
            reply_markup=_back("adm:users_menu"),
        )

    elif data.startswith("adm_adddays:"):
        tid = int(data.split(":", 1)[1])
        context.user_data["adm_await"]  = "adddays"
        context.user_data["adm_target"] = tid
        await q.edit_message_text(
            f"➕ چند روز به اشتراک کاربر `{tid}` اضافه بشه؟",
            parse_mode="Markdown",
            reply_markup=_back("adm:main")
        )

    elif data.startswith("adm_addcredits:"):
        tid = int(data.split(":", 1)[1])
        context.user_data["adm_await"]  = "addcredits"
        context.user_data["adm_target"] = tid
        await q.edit_message_text(
            f"💎 چند اعتبار قدیمی اینستاگرام به کاربر `{tid}` اضافه شود؟ (با انقضای قبلی)",
            parse_mode="Markdown",
            reply_markup=_back("adm:main")
        )

    elif data.startswith("adm_free_plan:"):
        tid = int(data.split(":", 1)[1])
        # اشتراک رایگان ۳۰ روز + ۳ اعتبار
        UserRepo.add_days(tid, 30)
        UserRepo.add_credits(tid, 3)
        await q.edit_message_text(
            f"🎁 اشتراک رایگان برای کاربر `{tid}` فعال شد:\n"
            f"✅ +۳۰ روز | 💎 +۳ اعتبار",
            parse_mode="Markdown",
            reply_markup=_back("adm:users_menu")
        )
        try:
            await context.bot.send_message(
                chat_id=tid,
                text="🎁 یه اشتراک رایگان برات فعال شد!\n💎 ۳ تحلیل رایگان داری. از /start شروع کن!"
            )
        except Exception:
            pass

    elif data.startswith("adm_orders:"):
        tid = int(data.split(":", 1)[1])
        await _show_user_orders(update, context, tid)

    elif data.startswith("adm_jobs:"):
        tid = int(data.split(":", 1)[1])
        await _show_user_jobs(update, context, tid)

    elif data.startswith("adm_approve:"):
        order_id = data.split(":", 1)[1]
        await _approve_order(update, context, order_id)

    elif data.startswith("adm_reject:"):
        order_id = data.split(":", 1)[1]
        context.user_data["adm_await"]           = "reject_note"
        context.user_data["adm_reject_order_id"] = order_id
        await q.edit_message_text(
            f"❌ دلیل رد سفارش `{order_id}` رو بنویس:\n(یا `skip` بزن)",
            parse_mode="Markdown"
        )

    elif data.startswith("adm_odetail:"):
        order_id = data.split(":", 1)[1]
        order = OrderRepo.get_by_order_id(order_id)
        if not order:
            await q.edit_message_text("سفارش پیدا نشد.", reply_markup=_back())
            return
        from app.services.receipt_review import send_order_review
        await send_order_review(context.bot, update.effective_user.id, order)

    else:
        await q.edit_message_text("گزینه ناشناخته.", reply_markup=_back())


# ════════════════════════════════════════════════════════════════
#  Text input router
# ════════════════════════════════════════════════════════════════
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return False
    _ensure_patched()
    text     = (update.message.text or "").strip() if update.message else ""
    await_key = context.user_data.get("adm_await")
    if not await_key:
        return False

    context.user_data.pop("adm_await", None)

    if await_key == "search_id":
        try:
            tid = int(text)
        except ValueError:
            await update.message.reply_text("آیدی باید عدد باشه.")
            return True
        await _show_user_detail_by_id(update, context, tid)
        return True

    if await_key == "search_username":
        users = UserRepo.search_by_username(text)
        if not users:
            await update.message.reply_text("کاربری پیدا نشد.",
                                            reply_markup=_back("adm:users_menu"))
            return True
        lines = []
        for u in users[:10]:
            uname   = f"@{u['username']}" if u.get("username") else "—"
            blocked = "🚫" if u.get("is_blocked") else "✅"
            lines.append(
                f"{blocked} {u.get('first_name','؟')} ({uname}) — `{u['telegram_user_id']}`"
            )
        await update.message.reply_text(
            "🔍 *نتایج:*\n\n" + "\n".join(lines) +
            "\n\n🔢 آیدی عددی رو بفرست برای جزئیات:",
            parse_mode="Markdown",
        )
        context.user_data["adm_await"] = "search_id"
        return True

    if await_key == "adddays":
        tid = context.user_data.pop("adm_target", None)
        try:
            days = int(text); assert days > 0
        except (ValueError, AssertionError):
            await update.message.reply_text("عدد مثبت وارد کن.")
            return True
        UserRepo.add_credits(tid, days)
        await update.message.reply_text(
            f"✅ {days} اعتبار به کاربر `{tid}` اضافه شد.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=tid,
                text=f"🎁 ادمین {days} اعتبار به حسابت اضافه کرد!"
            )
        except Exception:
            pass
        return True

    if await_key == "addcredits":
        tid = context.user_data.pop("adm_target", None)
        try:
            n = int(text); assert n > 0
        except (ValueError, AssertionError):
            await update.message.reply_text("عدد مثبت وارد کن.")
            return True
        UserRepo.add_credits(tid, n)
        await update.message.reply_text(
            f"✅ {n} اعتبار به کاربر `{tid}` اضافه شد.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=tid,
                text=f"🎁 ادمین {n} اعتبار به حسابت اضافه کرد!"
            )
        except Exception:
            pass
        return True

    if await_key == "reject_note":
        order_id = context.user_data.pop("adm_reject_order_id", "")
        note = "" if text.lower() == "skip" else text
        await _do_reject_order(update, context, order_id, note)
        return True

    if await_key == "broadcast":
        await _do_broadcast(update, context, text)
        return True

    return False


# ════════════════════════════════════════════════════════════════
#  توابع داخلی
# ════════════════════════════════════════════════════════════════
async def _send_stats_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now     = now_utc()
    total_u = UserRepo.count_total()
    online  = UserRepo.count_online(5) if hasattr(UserRepo, "count_online") else 0
    act24   = UserRepo.count_active_since((now - timedelta(hours=24)).isoformat())
    act7d   = UserRepo.count_active_since((now - timedelta(days=7)).isoformat())
    pending = OrderRepo.count_by_status("awaiting_review")
    paid    = OrderRepo.count_by_status("paid")
    rejected= OrderRepo.count_by_status("rejected")
    total_j = JobRepo.count_total()
    revenue = OrderRepo.revenue_total() if hasattr(OrderRepo, "revenue_total") else 0
    paid_td = OrderRepo.count_today_paid() if hasattr(OrderRepo, "count_today_paid") else 0
    jobs_td = JobRepo.count_today() if hasattr(JobRepo, "count_today") else 0

    text = (
        "📊 *آمار ردپاگرد*\n"
        f"📅 {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"👥 کل کاربران: *{total_u}*\n"
        f"🟢 آنلاین (۵ دقیقه): *{online}*\n"
        f"🔵 فعال ۲۴ ساعت: *{act24}*\n"
        f"🟡 فعال ۷ روز: *{act7d}*\n\n"
        f"💰 درآمد کل: *{revenue:,} تومان*\n"
        f"✅ پرداختی امروز: *{paid_td}*\n"
        f"🛒 در انتظار: *{pending}*\n"
        f"📦 کل پرداختی: *{paid}*\n"
        f"❌ ردشده: *{rejected}*\n\n"
        f"🔍 تحلیل امروز: *{jobs_td}*\n"
        f"💼 کل تحلیل‌ها: *{total_j}*"
    )
    total  = total_u
    kb     = _admin_main_menu(total, online)
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown",
                                                      reply_markup=kb)


async def _export_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now     = now_utc()
    q       = update.callback_query
    total   = UserRepo.count_total()
    online  = UserRepo.count_online(5) if hasattr(UserRepo, "count_online") else 0
    revenue = OrderRepo.revenue_total() if hasattr(OrderRepo, "revenue_total") else 0
    text = (
        "📤 *گزارش کامل ردپاگرد*\n"
        f"تاریخ: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"👥 کل کاربران: {total}\n"
        f"🟢 آنلاین: {online}\n"
        f"🔵 فعال ۲۴h: {UserRepo.count_active_since((now-timedelta(hours=24)).isoformat())}\n"
        f"🟡 فعال ۷d: {UserRepo.count_active_since((now-timedelta(days=7)).isoformat())}\n\n"
        f"💰 درآمد کل: {revenue:,} تومان\n"
        f"✅ پرداختی: {OrderRepo.count_by_status('paid')}\n"
        f"🛒 در انتظار: {OrderRepo.count_by_status('awaiting_review')}\n"
        f"❌ ردشده: {OrderRepo.count_by_status('rejected')}\n\n"
        f"💼 کل تحلیل‌ها: {JobRepo.count_total()}"
    )
    if q:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=_back())


async def _list_recent_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q     = update.callback_query
    users = UserRepo.list_recent(20) if hasattr(UserRepo, "list_recent") else []
    if not users:
        await q.edit_message_text("کاربری ثبت نشده.", reply_markup=_back("adm:users_menu"))
        return
    lines = []
    for u in users:
        uname   = f"@{u['username']}" if u.get("username") else "—"
        blocked = "🚫" if u.get("is_blocked") else "✅"
        ls      = (u.get("last_seen_at") or "")[:10]
        lines.append(
            f"{blocked} {u.get('first_name','؟')} ({uname})\n"
            f"   🆔 `{u['telegram_user_id']}` | 💎 {u.get('credits',0)} | {ls}"
        )
    await q.edit_message_text(
        "🕐 *آخرین کاربران:*\n\n" + "\n\n".join(lines) +
        "\n\n🔢 آیدی عددی رو بفرست برای جزئیات:",
        parse_mode="Markdown",
        reply_markup=_back("adm:users_menu")
    )
    context.user_data["adm_await"] = "search_id"


async def _list_online_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q      = update.callback_query
    from app.db.repos import get_connection, _rows
    cutoff = (now_utc() - timedelta(minutes=5)).isoformat()
    with get_connection() as conn:
        users = _rows(conn.execute(
            "SELECT * FROM users WHERE last_seen_at >= ? AND is_blocked=0"
            " ORDER BY last_seen_at DESC", (cutoff,)
        ).fetchall())
    if not users:
        await q.edit_message_text(
            "🟢 هیچ کاربری در ۵ دقیقه اخیر فعال نبوده.",
            reply_markup=_back("adm:users_menu")
        )
        return
    lines = []
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        ls    = (u.get("last_seen_at") or "")[:16]
        lines.append(f"🟢 {u.get('first_name','؟')} ({uname}) — `{u['telegram_user_id']}` | {ls}")
    await q.edit_message_text(
        f"🟢 *کاربران آنلاین ({len(users)} نفر):*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_back("adm:users_menu")
    )


async def _list_blocked_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q     = update.callback_query
    users = UserRepo.list_blocked() if hasattr(UserRepo, "list_blocked") else []
    if not users:
        await q.edit_message_text("هیچ کاربر مسدودی نیست! 🎉",
                                  reply_markup=_back("adm:users_menu"))
        return
    lines = []
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(f"🚫 {u.get('first_name','؟')} ({uname}) — `{u['telegram_user_id']}`")
    await q.edit_message_text(
        "🚫 *کاربران مسدود:*\n\n" + "\n".join(lines) +
        "\n\n🔢 آیدی عددی رو بفرست برای مدیریت:",
        parse_mode="Markdown",
        reply_markup=_back("adm:users_menu")
    )
    context.user_data["adm_await"] = "search_id"


async def _show_user_detail_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   tid: int) -> None:
    u = UserRepo.get_by_telegram_id(tid)
    if not u:
        if update.message:
            await update.message.reply_text("کاربری با این آیدی پیدا نشد.")
        return
    orders   = OrderRepo.list_by_user(tid)
    jobs_cnt = JobRepo.count_by_user(tid)
    text = (
        f"{_fmt_user(u)}\n\n"
        f"🛒 سفارشات: {len(orders)} | 🔍 تحلیل‌ها: {jobs_cnt}\n"
        f"📅 عضویت از: {(u.get('created_at') or '')[:10]}"
    )
    kb = _admin_user_actions(tid, bool(u.get("is_blocked")))
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown",
                                                      reply_markup=kb)


async def _show_user_orders(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             tid: int) -> None:
    q      = update.callback_query
    orders = OrderRepo.list_by_user(tid)
    if not orders:
        await q.edit_message_text("این کاربر سفارشی نداره.", reply_markup=_back())
        return
    lines  = [_fmt_order(o) for o in orders[-10:]]
    await q.edit_message_text(
        f"📋 *سفارشات کاربر {tid}:*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_back()
    )


async def _show_user_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           tid: int) -> None:
    q    = update.callback_query
    jobs = JobRepo.list_by_user(tid) if hasattr(JobRepo, "list_by_user") else []
    if not jobs:
        await q.edit_message_text("تاریخچه تحلیلی نداره.", reply_markup=_back())
        return
    lines = []
    for j in jobs:
        lines.append(
            f"🔍 `{j.get('target_instagram_username','?')}` — {j.get('status','?')}\n"
            f"   {(j.get('created_at') or '')[:16]} | {j.get('result_summary','')}"
        )
    await q.edit_message_text(
        f"🔍 *تحلیل‌های کاربر {tid}:*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_back()
    )


async def _show_pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q      = update.callback_query
    orders = OrderRepo.list_awaiting_review()
    if not orders:
        await q.edit_message_text("هیچ سفارش در انتظاری نیست! ✅", reply_markup=_back())
        return
    from app.services.receipt_review import send_order_review
    sent = 0
    for order in orders:
        try:
            await send_order_review(context.bot, update.effective_user.id, order)
            sent += 1
        except Exception as exc:
            logger.warning("Receipt delivery failed for order %s (%s)", order.get("order_id"), type(exc).__name__)
    await q.edit_message_text(
        f"📋 {sent} سفارش از {len(orders)} سفارش ارسال شد.",
        reply_markup=_back(),
    )


async def _show_all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q      = update.callback_query
    orders = OrderRepo.list_all(30) if hasattr(OrderRepo, "list_all")              else OrderRepo.list_awaiting_review()
    if not orders:
        await q.edit_message_text("سفارشی ثبت نشده.", reply_markup=_back())
        return
    lines = [_fmt_order(o) for o in orders[:15]]
    await q.edit_message_text(
        f"📋 *آخرین {min(len(orders),15)} سفارش:*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_back()
    )


async def _approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          order_id: str) -> None:
    from app.services.payment_service import PaymentService
    q        = update.callback_query
    admin_id = update.effective_user.id
    result   = PaymentService.approve_order(order_id, admin_id)
    if not result:
        await q.edit_message_text(
            f"⚠️ سفارش `{order_id}` قبلاً پردازش شده یا پیدا نشد.",
            parse_mode="Markdown"
        )
        return
    await q.edit_message_text(f"✅ سفارش `{order_id}` تأیید شد.", parse_mode="Markdown")
    uid = result.get("telegram_user_id")
    if uid:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"✅ پرداخت سفارش `{order_id}` تأیید شد!\n💎 اشتراکت فعاله. از /start شروع کن!",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning("Could not notify user %s: %s", uid, e)


async def _do_reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            order_id: str, note: str) -> None:
    from app.services.payment_service import PaymentService
    result = PaymentService.reject_order(order_id, update.effective_user.id, note)
    if not result:
        await update.message.reply_text(
            f"⚠️ سفارش `{order_id}` قبلاً پردازش شده.", parse_mode="Markdown"
        )
        return
    await update.message.reply_text(f"❌ سفارش `{order_id}` رد شد.", parse_mode="Markdown")
    uid    = result.get("telegram_user_id")
    reason = f"دلیل: {note}" if note else ""
    if uid:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"❌ پرداخت سفارش `{order_id}` تأیید نشد.\n{reason}\n\nبا پشتیبانی تماس بگیر.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning("Could not notify user %s: %s", uid, e)


async def _do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         text: str) -> None:
    if not text or text.strip() == "skip":
        await update.message.reply_text("پیام خالی. لغو شد.")
        return
    from app.db.repos import get_connection, _rows
    with get_connection() as conn:
        all_users = _rows(conn.execute(
            "SELECT telegram_user_id, is_blocked FROM users"
        ).fetchall())
    sent = 0; failed = 0
    for u in all_users:
        if u.get("is_blocked"):
            continue
        try:
            await context.bot.send_message(chat_id=u["telegram_user_id"], text=text)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"📢 پیام همگانی ارسال شد.\n✅ موفق: {sent} | ❌ ناموفق: {failed}"
    )
