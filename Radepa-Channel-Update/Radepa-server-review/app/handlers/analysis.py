# === app/handlers/analysis.py ===
from __future__ import annotations
import re
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from app.db.repos import UserRepo, JobRepo
from app.services.job_service import JobService
from app.services.subscription_service import SubscriptionService
from app.utils.texts_fa import (SEND_INSTAGRAM_USERNAME, ANALYSIS_STARTED,
    ANALYSIS_NO_RESULTS, ANALYSIS_FAILED, NO_CREDITS, SUBSCRIPTION_EXPIRED,
    INVALID_USERNAME, BLOCKED)
from app.utils.keyboards import main_menu_keyboard, back_to_main_keyboard
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)
_IG_RE = re.compile(r'^[a-zA-Z0-9_.]{1,30}$')

# ── تشخیص نوع منبع ──────────────────────────────────────────

def _classify(source: Dict[str, Any]) -> str:
    link = source.get("link", "")
    snippet = source.get("snippet", "") or ""
    pattern = source.get("query_pattern", "")
    if "/reel/" in link:
        return "reel"
    if "/p/" in link:
        return "post"
    # Search snippets do not establish who authored a comment.
    if link.rstrip("/").endswith(source.get("username", "___NONE___")):
        return "profile"
    return "mention"

def _extract_mentioned_ids(sources: List[Dict[str, Any]]) -> List[str]:
    ids = set()
    for s in sources:
        found = re.findall(r'@([a-zA-Z0-9_.]{2,30})', s.get("snippet", "") or "")
        ids.update(found)
    return sorted(ids)

# ── فرمت‌های نمایش ──────────────────────────────────────────

def _format_summary(username: str, sources: List[Dict[str, Any]]) -> str:
    total = len(sources)
    posts   = [s for s in sources if _classify(s) in ("post","reel")]
    comments= []
    mentions= [s for s in sources if _classify(s) == "mention"]
    profiles= [s for s in sources if _classify(s) == "profile"]
    ids     = _extract_mentioned_ids(sources)

    lines = [
        f"🔎 *تحلیل ردپای عمومی*",
        f"👤 آیدی: `{username}`",
        f"━━━━━━━━━━━━━━━",
        f"",
        f"📊 *خلاصه یافته‌ها:*",
        f"• کل نتایج: *{total}* مورد",
        f"• پست / ریل: *{len(posts)}* مورد",
        f"• اشاره‌ها و نتایج دیگر: *{len(comments) + len(mentions)}* مورد",
        f"• پروفایل: *{len(profiles)}* مورد",
        f"",
    ]

    if ids:
        lines.append(f"🏷 *آیدی‌های مرتبط:*")
        for i, uid in enumerate(ids[:8], 1):
            safe_uid = uid.replace('_', r'\_')
            lines.append(f"  {i}. @{safe_uid}")
        lines.append("")

    lines += [
        f"━━━━━━━━━━━━━━━",
        f"⚠️ نتایج احتمالی از داده‌های عمومی‌اند — قطعی نیستن.",
    ]
    return "\n".join(lines)


def _format_links(username: str, sources: List[Dict[str, Any]]) -> str:
    lines = [
        f"🔗 لینک‌های یافت‌شده",
        f"👤 آیدی: {username}",
        f"━━━━━━━━━━━━━━━",
        f"",
    ]
    for i, s in enumerate(sources, 1):
        link = s.get("link", "")
        title = (s.get("title", "") or "بدون عنوان")[:50]
        stype = _classify(s)
        icon = {"post":"📸","reel":"🎬","comment":"💬","profile":"👤","mention":"📌"}.get(stype,"🔹")
        src = s.get("source","")
        src_icon = "🟢" if src == "duckduckgo" else "🔵"
        lines.append(f"{icon} {i}. {title}")
        lines.append(f"   {src_icon} {link}")
        lines.append("")
    lines.append("⚠️ قطعه‌متن موتور جست‌وجو، مدرک ارسال کامنت توسط صاحب آیدی نیست.")
    return "\n".join(lines)


def _format_comments(username: str, sources: List[Dict[str, Any]]) -> str:
    lines = [
        f"📝 *قطعه‌متن‌های نتایج جست‌وجو*",
        f"👤 آیدی: `{username}`",
        f"━━━━━━━━━━━━━━━",
        f"",
    ]
    relevant = [s for s in sources if s.get("snippet") and s["snippet"] != "—"]
    if not relevant:
        lines.append("متنی برای نمایش پیدا نشد.")
    else:
        for i, s in enumerate(relevant, 1):
            snippet = (s.get("snippet") or "").strip()
            link = s.get("link","")
            stype = _classify(s)
            icon = {"post":"📸","reel":"🎬","comment":"💬","mention":"📌"}.get(stype,"🔹")
            lines.append(f"{icon} *نتیجه {i}:*")
            safe_snippet = snippet[:200].replace('_',r'\_').replace('*',r'\*').replace('`',r'\`').replace('[',r'\[')
            lines.append(f'"{safe_snippet}"')
            lines.append(f"🔗 {link}")
            lines.append("")
    lines.append("⚠️ این متن‌ها ممکن است درباره آیدی باشند؛ نویسندگی کامنت را تأیید نمی‌کنند.")
    return "\n".join(lines)


def _result_keyboard(username: str, job_id: int, active: str) -> InlineKeyboardMarkup:
    def btn(label, view):
        mark = "✅ " if view == active else ""
        return InlineKeyboardButton(f"{mark}{label}", callback_data=f"result:{view}:{job_id}:{username}")
    return InlineKeyboardMarkup([
        [btn("📋 خلاصه", "summary"), btn("🔗 لینک‌ها", "links"), btn("📝 قطعه‌متن‌ها", "comments")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu:main")],
    ])

# ── چانک ────────────────────────────────────────────────────

def _chunk(text: str, size: int = 4000) -> List[str]:
    chunks = []
    while text:
        chunks.append(text[:size])
        text = text[size:]
    return chunks

# ── هندلرها ─────────────────────────────────────────────────

async def analyze_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    user = update.effective_user
    if not user: return
    db_user = UserRepo.get_by_telegram_id(user.id)
    if db_user and db_user.get("is_blocked"):
        await query.edit_message_text(BLOCKED); return
    can, reason = SubscriptionService.check_can_analyze(user.id)
    if not can:
        msg = BLOCKED if reason=="blocked" else (SUBSCRIPTION_EXPIRED if reason=="expired" else NO_CREDITS)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return
    context.user_data["awaiting_instagram_username"] = True
    await query.edit_message_text(SEND_INSTAGRAM_USERNAME, parse_mode="Markdown",
        reply_markup=back_to_main_keyboard())


async def receive_username_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_instagram_username"): return
    user = update.effective_user
    if not user or not update.message or not update.message.text: return
    raw = update.message.text.strip().lstrip("@").lower()
    if not _IG_RE.match(raw):
        await update.message.reply_text(INVALID_USERNAME, reply_markup=back_to_main_keyboard())
        return
    context.user_data.pop("awaiting_instagram_username", None)
    can, reason = SubscriptionService.check_can_analyze(user.id)
    if not can:
        msg = SUBSCRIPTION_EXPIRED if reason=="expired" else NO_CREDITS
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    working = await update.message.reply_text(
        f"⏳ در حال جستجوی `{raw}` هستم...\nچند ثانیه صبر کن 🔄",
        parse_mode="Markdown")

    job_service: JobService = context.bot_data["job_service"]
    result = await job_service.run_analysis(user.id, raw)

    try: await working.delete()
    except: pass

    if result["status"] == "failed":
        await update.message.reply_text(ANALYSIS_FAILED, reply_markup=main_menu_keyboard())
        logger.warning("Analysis failed for user=%d target=%s", user.id, raw)
        return
    if result["status"] == "no_credit":
        await update.message.reply_text(NO_CREDITS, parse_mode="Markdown",
            reply_markup=main_menu_keyboard())
        return

    sources = result["sources"]
    job_id  = result["job_id"]

    logger.info("Analysis done user=%d target=%s results=%d job=%s",
                user.id, raw, len(sources), job_id)

    if not sources:
        await update.message.reply_text(
            ANALYSIS_NO_RESULTS.format(username=raw),
            parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    # ذخیره sources در context برای دکمه‌ها
    context.user_data[f"sources_{job_id}"] = sources

    text = _format_summary(raw, sources)
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=_result_keyboard(raw, job_id, "summary"),
        disable_web_page_preview=True)


async def result_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های خلاصه / لینک‌ها / کامنت‌ها"""
    query = update.callback_query
    if not query: return
    await query.answer()

    # format: result:{view}:{job_id}:{username}
    parts = (query.data or "").split(":", 3)
    if len(parts) < 4: return
    _, view, job_id_str, username = parts
    try:
        job_id = int(job_id_str)
    except ValueError:
        return
    job = JobRepo.get(job_id)
    if not job or not update.effective_user or job["telegram_user_id"] != update.effective_user.id:
        await query.answer("به این نتیجه دسترسی نداری.", show_alert=True)
        return

    # برگرفتن sources از context یا DB
    sources = context.user_data.get(f"sources_{job_id}")
    if not sources:
        await query.answer("اطلاعات منقضی شده. دوباره جستجو کن.", show_alert=True)
        return

    if view == "summary":
        text = _format_summary(username, sources)
    elif view == "links":
        text = _format_links(username, sources)
    elif view == "comments":
        text = _format_comments(username, sources)
    else:
        return

    chunks = _chunk(text)
    try:
        await query.edit_message_text(
            chunks[0],
            reply_markup=_result_keyboard(username, job_id, view),
            disable_web_page_preview=True)
        for chunk in chunks[1:]:
            await query.message.reply_text(chunk,
                disable_web_page_preview=True)
    except Exception as e:
        logger.error("result_view_callback error: %s", e)
