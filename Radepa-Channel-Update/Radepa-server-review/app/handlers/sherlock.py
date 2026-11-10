"""Explicit private-chat command; ordinary text is never a Sherlock input."""
from __future__ import annotations

import asyncio
from telegram.ext import ContextTypes

from app.db.repos import UserRepo
from app.services.sherlock_service import AdmissionRejected, SherlockResult, normalize_username
from app.utils.keyboards import back_to_main_keyboard
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)
GUIDE = ('🔎 جستجوی یوزرنیم در وب\n\n'
         'فرمان زیر را با یک یوزرنیم بفرستید:\n/sherlock YOUR_USERNAME\n'
         'یک @ در ابتدای نام پذیرفته می‌شود. فقط حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط؛ حداکثر ۶۴ کاراکتر.\n'
         'این جستجو رایگان است و اعتبار تحلیل مصرف نمی‌کند.\n'
         'پیام عادی چت، درخواست جستجو نیست.\n'
         '⚠️ یکسان بودن یوزرنیم، مالکیت مشترک حساب‌ها را ثابت نمی‌کند.')


async def _allowed(update):
    message, user = update.effective_message, update.effective_user
    if not message or not user:
        return False
    if not update.effective_chat or update.effective_chat.type != 'private':
        await message.reply_text('این جستجو فقط در گفت‌وگوی خصوصی ربات فعال است.')
        return False
    account = UserRepo.get_by_telegram_id(user.id)
    if not account:
        await message.reply_text('ابتدا از منو /start را انتخاب کنید.')
        return False
    if account.get('is_blocked'):
        await message.reply_text('این حساب غیرفعال است.')
        return False
    return True


async def sherlock_prompt(update, context: ContextTypes.DEFAULT_TYPE):
    if not await _allowed(update):
        return
    service = context.bot_data.get('sherlock_service')
    text = GUIDE
    if not service or not service.enabled:
        text += '\n\nاین قابلیت فعلاً غیرفعال است.'
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=None, reply_markup=back_to_main_keyboard())
    else:
        await update.effective_message.reply_text(text, parse_mode=None, reply_markup=back_to_main_keyboard())


async def sherlock_prompt_callback(update, context):
    if update.callback_query:
        await update.callback_query.answer()
    await sherlock_prompt(update, context)


def format_report(username: str, result: SherlockResult, *, links_per_message=5, max_links=50):
    found = result.found
    if result.status == 'complete':
        status = ('جستجو کامل شد.' if found else 'جستجو کامل شد و نتیجه‌ای پیدا نشد.')
    elif result.status == 'timeout':
        status = 'جستجو ناقص ماند؛ مهلت کل اجرا تمام شد.'
    elif result.status == 'partial':
        status = 'جستجو ناقص بود؛ پاسخ بعضی سایت‌ها نامشخص، مسدود یا ناموفق بود.'
    elif result.status == 'unavailable':
        status = 'جستجو اجرا نشد؛ ابزار Sherlock در دسترس نیست.'
    else:
        status = 'جستجو کامل نشد؛ اجرا یا دریافت خروجی معتبر ناموفق بود.'
    lines = [f'🔎 گزارش جستجوی یوزرنیم در وب\nیوزرنیم: {username}', status]
    if result.records:
        counts = result.status_counts
        uncertain = len(result.records) - counts.get('Claimed', 0) - counts.get('Available', 0)
        lines.append(f'سایت‌های دارای خروجی: {len(result.records)} | لینک‌های احتمالی: {len(found)}\n'
                     f'وضعیت Available: {counts.get("Available", 0)} | وضعیت‌های دیگر/نامشخص: {uncertain}')
    if result.status != 'complete' and not found:
        lines.append('نبود لینک در این پاسخ، به معنی نبود حساب نیست؛ بررسی کامل نشده است.')
    if len(found) > max_links:
        lines.append(f'برای کوتاه‌ماندن گزارش، فقط {max_links} لینک اول از {len(found)} لینک نمایش داده می‌شود.')
    lines.append('⚠️ یکسان بودن یوزرنیم، مالکیت مشترک حساب‌ها را ثابت نمی‌کند؛ یافته‌ها احتمالی‌اند.')
    pages = ['\n\n'.join(lines)]
    page = ''
    count = 0
    for index, row in enumerate(found[:max_links], 1):
        block = f'{index}. {row.name}\n{row.url}\n\n'
        if page and (count >= links_per_message or len((page + block).encode('utf-16-le')) // 2 > 3500):
            pages.append(page.rstrip())
            page, count = '', 0
        page += block
        count += 1
    if page:
        pages.append(page.rstrip())
    return pages


async def _run_search(service, permit, message):
    try:
        try:
            result = await service.execute(permit)
        except Exception as exc:
            logger.warning('Sherlock execution failed (%s)', type(exc).__name__)
            result = SherlockResult('failed', reason='execution_error')
        account = UserRepo.get_by_telegram_id(permit.user_id)
        if not account or account.get('is_blocked'):
            return
        async def deliver():
            for index, page in enumerate(format_report(permit.username, result)):
                if index:
                    await asyncio.sleep(1)
                await message.reply_text(page, parse_mode=None, disable_web_page_preview=True)
        await asyncio.wait_for(deliver(), timeout=30)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning('Sherlock background job failed (%s)', type(exc).__name__)
    finally:
        service.finish(permit)


async def sherlock_command(update, context: ContextTypes.DEFAULT_TYPE):
    if not await _allowed(update):
        return
    message = update.effective_message
    try:
        if len(context.args) != 1:
            raise ValueError('Expected one username')
        username = normalize_username(context.args[0])
    except ValueError:
        await message.reply_text('یوزرنیم نامعتبر است. فقط یک نام بفرستید؛ مثال:\n/sherlock example_user', parse_mode=None)
        return
    service = context.bot_data.get('sherlock_service')
    if not service:
        await message.reply_text('این قابلیت فعلاً غیرفعال است.')
        return
    try:
        permit = service.reserve(update.effective_user.id, username)
    except AdmissionRejected as exc:
        text = {'disabled':'این قابلیت فعلاً غیرفعال است.',
                'busy':'یک جستجوی شما هنوز در حال اجراست.',
                'full':'ظرفیت جستجو فعلاً پر است؛ کمی بعد دوباره تلاش کنید.',
                'rate_limited':f'برای درخواست بعدی حدود {exc.retry_after} ثانیه صبر کنید.'}[exc.reason]
        await message.reply_text(text)
        return
    work = None
    try:
        await message.reply_text('⏳ در حال جستجو…')
        work = _run_search(service, permit, message)
        task = context.application.create_task(work, update=update, name='sherlock-search')
        service.track(task, permit)
    except asyncio.CancelledError:
        if work:
            work.close()
        service.finish(permit)
        raise
    except Exception as exc:
        if work:
            work.close()
        service.finish(permit)
        logger.warning('Sherlock job scheduling failed (%s)', type(exc).__name__)
