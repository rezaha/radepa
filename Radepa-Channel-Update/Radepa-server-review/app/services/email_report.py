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

LABELS = {
    'address_risk_status': 'ریسک آدرس', 'domain_risk_status': 'ریسک دامنه',
    'score': 'امتیاز کیفیت', 'is_free_email': 'سرویس رایگان',
    'is_disposable_email': 'ایمیل موقت', 'is_catchall_email': 'دامنه پذیرنده همه آدرس‌ها',
    'is_role_email': 'آدرس سازمانی عمومی', 'is_username_suspicious': 'نام کاربری مشکوک',
    'is_mailbox_full': 'صندوق پر', 'status': 'وضعیت', 'status_detail': 'جزئیات',
    'is_format_valid': 'قالب معتبر', 'is_smtp_valid': 'SMTP معتبر', 'is_mx_valid': 'MX معتبر',
}

def report_lines(email, result, source_limit=None):
    from app.services.email_lookup import EmailSummary
    if not isinstance(result, EmailSummary):
        result = EmailSummary(result, None)
    leak, abstract = result.leakcheck, result.abstract
    stamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M %z")
    lines = ["گزارش امنیت ایمیل | ردپا", "━━━━━━━━━━━━━━━━", f"ایمیل: {mask_email(email)}",
             f"زمان بررسی: {stamp}", "", "نشت داده — شمارش جداگانه هر سرویس:"]
    if leak is None:
        lines.append("LeakCheck: در دسترس نیست؛ نتیجه نامشخص است.")
    else:
        lines.append(f"LeakCheck: تعداد رکوردهای گزارش‌شده: {leak.found}")
        if leak.found:
            lines += ["⚠️ هشدار: ایمیل در منابع نشت داده مشاهده شده است.",
                      "این نتیجه به‌تنهایی افشای رمز فعلی یا هک شدن حساب شما را ثابت نمی‌کند."]
        else:
            lines.append("در این منبع رکوردی پیدا نشد؛ نبود نتیجه، امنیت کامل را تضمین نمی‌کند.")
        if leak.fields:
            lines.append("نوع داده‌های گزارش‌شده (LeakCheck): " + ", ".join(leak.fields)[:800])
    if abstract is None:
        lines.append("AbstractAPI: در دسترس نیست یا تنظیم نشده؛ نتیجه نامشخص است.")
    else:
        count = abstract.found if abstract.found is not None else 'ارائه نشده'
        lines.append(f"AbstractAPI: تعداد نشت‌های گزارش‌شده: {count}")
    lines.append("تعدادهای دو سرویس به‌علت احتمال هم‌پوشانی و تفاوت تعریف رکورد جمع نشده‌اند.")
    # Match normalized names, retaining provider provenance and distinct dates.
    sources = {}
    for provider, summary in (("LeakCheck", leak), ("AbstractAPI", abstract)):
        for name, date in (summary.sources if summary else ()):
            key = " ".join(name.split()).casefold()
            if not key:
                continue
            entry = sources.setdefault(key, [name.strip(), [], []])
            if date and date not in entry[1]:
                entry[1].append(date)
            if provider not in entry[2]:
                entry[2].append(provider)
    lines += ["", "منابع گزارش‌شده (بدون تکرار نام):"]
    entries = list(sources.values())
    shown = entries if source_limit is None else entries[:source_limit]
    lines += [f"• {name[:100]} | تاریخ: {', '.join(dates) or 'نامشخص'} | منبع: {', '.join(providers)}"
              for name, dates, providers in shown]
    if not entries:
        lines.append("جزئیات منبع ارائه نشده است.")
    if source_limit is not None and len(entries) > source_limit:
        lines.append("ادامه منابع در فایل متنی پیوست آمده است.")
    for title, field in (("ریسک", "risk"), ("کیفیت", "quality"), ("قابلیت تحویل", "deliverability")):
        lines += ["", title + " — AbstractAPI:"]
        values = getattr(abstract, field) if abstract else ()
        lines.extend(f"• {LABELS.get(key, key)}: {value}" for key, value in values)
        if not values:
            lines.append("نامشخص؛ داده‌ای در دسترس نیست.")
    lines += ["", "🛡 اقدامات پیشنهادی:", *ACTIONS, "", "محدودیت گزارش:",
              "این گزارش خلاصه API عمومی است؛ مقدار واقعی رمز، شماره تلفن و رکورد خام را ارائه نمی‌کند.",
              "وجود نتیجه، هویت صاحب ایمیل یا وضعیت فعلی حساب را ثابت نمی‌کند.",
              "Powered by LeakCheck — https://leakcheck.io",
              "AbstractAPI — https://www.abstractapi.com"]
    return lines

def render_html(email, result):
    # Fit complete HTML entities/tags inside Telegram's message limit, even with
    # adversarial source names. The TXT retains all returned source metadata.
    for limit in range(8, -1, -1):
        lines = report_lines(email, result, limit)
        body = "<b>🔐 " + html.escape(lines[0]) + "</b>\n" + "\n".join(html.escape(line) for line in lines[1:])
        if len(body.encode("utf-16-le")) // 2 <= 3900:
            return body
    # Keep Telegram concise while the attachment retains the complete metadata.
    lines = report_lines(email, result, 0)
    body = "\n".join(lines)
    body = body[:1400] + "\nگزارش کامل هر دو منبع در فایل TXT پیوست آمده است."
    while len(html.escape(body).encode("utf-16-le")) // 2 > 3900:
        body = body[:len(body) - 100]
    return html.escape(body)

def render_txt(email, result):
    return "\n".join(report_lines(email, result)) + "\n"
