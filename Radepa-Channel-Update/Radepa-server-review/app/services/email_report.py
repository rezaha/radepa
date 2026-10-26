"""Render only public breach metadata, never raw credentials."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from app.utils.email_utils import mask_email

ACTIONS = (
    "۱. رمز حساب‌های مرتبط و رمزهای تکراری را با رمزهای قوی و منحصربه‌فرد عوض کنید.",
    "۲. تأیید دومرحله‌ای را فعال کنید؛ ترجیحاً برنامه احراز هویت یا کلید امنیتی.",
    "۳. نشست‌ها و ورودهای ناشناس و تنظیمات بازیابی حساب را بررسی کنید.",
    "۴. مراقب پیام‌های فیشینگ باشید و رمز یا کد ورود را در اختیار کسی نگذارید.",
)

def report_lines(email, result, source_limit=None):
    stamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M %z")
    lines = ["گزارش امنیت ایمیل | ردپا", "━━━━━━━━━━━━━━━━", f"ایمیل: {mask_email(email)}",
             f"زمان بررسی: {stamp}", f"تعداد رکوردهای گزارش‌شده: {result.found}", ""]
    if result.found:
        lines += ["⚠️ هشدار: ایمیل در منابع نشت داده مشاهده شده است.",
                  "این نتیجه به‌تنهایی افشای رمز فعلی یا هک شدن حساب شما را ثابت نمی‌کند."]
    else:
        lines += ["در این منبع رکوردی پیدا نشد؛ نبود نتیجه، نبود نشت یا امنیت کامل را تضمین نمی‌کند."]
    if result.fields:
        lines += ["", "نوع داده‌های گزارش‌شده: " + ", ".join(result.fields)[:800]]
    lines += ["", "منابع گزارش‌شده:"]
    sources = result.sources if source_limit is None else result.sources[:source_limit]
    lines += [f"• {name[:100]} | تاریخ: {date[:20] or 'نامشخص'}" for name, date in sources]
    if not sources:
        lines.append("جزئیات منبع ارائه نشده است.")
    if source_limit is not None and len(result.sources) > source_limit:
        lines.append("ادامه منابع در فایل متنی پیوست آمده است.")
    lines += ["", "🛡 اقدامات پیشنهادی:", *ACTIONS, "", "محدودیت گزارش:",
              "این گزارش خلاصه API عمومی است؛ مقدار واقعی رمز، شماره تلفن و رکورد خام را ارائه نمی‌کند.",
              "وجود نتیجه، هویت صاحب ایمیل یا وضعیت فعلی حساب را ثابت نمی‌کند.",
              "Powered by LeakCheck — https://leakcheck.io"]
    return lines

def render_html(email, result):
    # Fit complete HTML entities/tags inside Telegram's message limit, even with
    # adversarial source names. The TXT retains all returned source metadata.
    from dataclasses import replace
    short = replace(result, fields=tuple(x[:32] for x in result.fields[:6]))
    for limit in range(8, -1, -1):
        lines = report_lines(email, short, limit)
        if short.fields != result.fields:
            lines.append("فهرست کامل نوع داده‌ها در فایل پیوست است.")
        body = "<b>🔐 " + html.escape(lines[0]) + "</b>\n" + "\n".join(html.escape(line) for line in lines[1:])
        if len(body.encode("utf-16-le")) // 2 <= 3900:
            return body
    raise ValueError("Report exceeds Telegram limit")

def render_txt(email, result):
    return "\n".join(report_lines(email, result)) + "\n"
