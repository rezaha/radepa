# staging با Python 3.10 پایدار و برنامه جایگزینی محیط

این سند برنامه و نتایج اولیه پیش از نصب است. پس از آن، مدیر پروژه staging سرور را تأیید و نصب را با مجوز جدا انجام داد؛ [ثبت نصب و پذیرش اولیه](DEPLOYMENT_ACCEPTANCE_FA.md) شامل شواهد جدید و مانع باقی‌مانده HTTP 403 اینستاگرام است.

این راهنما ادامه پذیرش بسته ثابت d2dfd8b است؛ هیچ مجوزی برای deploy یا تغییر Production ایجاد نمی‌کند. در این مرحله /opt/radepa/venv، سرویس و دیتابیس سرور اصلی دست‌نخورده می‌مانند.

## وضعیت گزارش‌شده سرور

در ۲۰۲۶-۱۱-۰۱، مدیر پروژه نتیجه Preflight واقعی را گزارش کرد: Ubuntu 22.04، Python سیستم 3.10.12 پایدار، Python venv برابر 3.11.0rc1، سرویس active، WorkingDirectory=/opt/radepa و baseline=admin-support با fingerprint پشتیبانی‌شده. BLOCKED فقط ناشی از Python پیش‌انتشار محیط فعال است. این اطلاعات گزارش کاربر است؛ از این محیط اتصال مستقل به سرور انجام نشده است.

بنابراین مانع «baseline ناشناخته» طبق شواهد ارائه‌شده رفع شده، اما venv قدیمی برای پذیرش نسخه جدید مناسب نیست. آن را ارتقا، حذف یا بازسازی درجا نکنید. فعال و سالم بودن ربات فعلی با مناسب‌بودن محیط آن برای انتشار جدید دو بررسی جدا هستند. شرط پایداربودن Python در Preflight حذف نمی‌شود؛ خروجی BLOCKED فعلی تا جایگزینی مجاز بعدی حفظ می‌شود.

## انتخاب صریح Python و محیط مستقل

ابزار stage از sys.executable برای ساخت venv استفاده می‌کند؛ activate کردن venv قدیمی یا فراخوانی /opt/radepa/venv/bin/python اشتباه است. در VM مستقل Ubuntu 22.04، مراحل دریافت بسته، checksum و نصب کتابخانه‌های Chromium در [STAGING_ACCEPTANCE_FA.md](STAGING_ACCEPTANCE_FA.md) را انجام دهید. فقط انتخاب Python را صریح کنید:

```bash
/usr/bin/python3.10 -I -B - <<'PY'
import sys
assert sys.version_info[:3] == (3, 10, 12), sys.version
assert sys.version_info.releaselevel == 'final', sys.version
print('Stable staging interpreter:', sys.version.split()[0])
PY
```

این pin برای بازتولید آزمایش 3.10.12 است؛ نسخه patch پایدار جدیدتر نیز باید تست کامل خودش را بگذراند. از پوشه استخراج‌شده radepa-release، فقط روی VM آزمایشی:

```bash
/usr/bin/python3.10 -B tools/release_manager.py stage \
  --source "$PWD" --root "$HOME/radepa-python310-stages"
```

venv، مرورگر، SQLite و لاگ تازه در پوشه یکتای همین root ساخته می‌شوند. هیچ اتصال polling واقعی Telegram انجام نمی‌شود و کلیدهای واقعی جایگزین داده ساختگی می‌شوند. مرحله با --without-browser صرفاً برای تشخیص سازگاری Python است، نه مجوز پذیرش مرورگر یا نصب.

برای تشخیص Python بدون دانلود مرورگر، در همین VM می‌توان مرحله جدا ساخت:

```bash
/usr/bin/python3.10 -B tools/release_manager.py stage \
  --source "$PWD" --root "$HOME/radepa-python310-offline" --without-browser
```

پس از موفقیت مرحله پیش‌فرض، بررسی کامل STAGING_EVIDENCE_PASS در راهنمای پذیرش را اجرا کنید؛ ready.json باید browser=true و Python پایدار، و health.json باید chromium_local_fixture=passed و startup_without_playwright=passed داشته باشد. وجود Chromium سیستم یا موفقیت pip install playwright به‌تنهایی تأیید مرورگر رسمی نیست.

## Chromium و شبکه

مرورگر موردنیاز را خود Playwright 1.64.1 از CDN رسمی یا mirror داخلی تأییدشده نصب می‌کند. install --dry-run chromium URLهای دقیق را بدون دانلود نشان می‌دهد. اگر HTTP 403 از policy دریافت شد، همان مرحله ناموفق می‌ماند؛ ready.json نسازید و browser را دستی true نکنید. مسیرهای مجاز، CA و متغیرهای رسمی download host در راهنمای پذیرش مستند شده‌اند. TLS و proxy حفظ می‌شوند. در این کار هیچ تغییری در policy شبکه صورت نگرفته است.

## جایگزینی آینده و بازگشت؛ توضیح رفتار موجود، نه دستور اجرا

کد فعلی نصب‌کننده برای این الگو نیاز به تغییر ندارد:

1. مرحله جدید با /usr/bin/python3.10 در مسیر پایدار و نهایی زیر /opt/radepa-releases ساخته و تمام تست‌ها، browser smoke و شواهد نسخه Python تأیید می‌شوند. اجرای پذیرش اولیه روی VM جدا، مجوز ساخت این مرحله روی سرور اصلی نیست؛ آن اقدام بعداً جداگانه مجاز می‌شود.
2. venv ساخته‌شده در VM آزمایشی را به سرور کپی یا جابه‌جا نکنید. مسیرهای venv و binary مرورگر و وابستگی‌های سیستم به محیط وابسته‌اند؛ مرحله مقصد باید در همان مسیر نهایی دوباره ساخته و تأیید شود. جابه‌جایی stage پس از ساخت مجاز نیست.
3. تنها پس از مجوز جداگانه نصب Production، نصب‌کننده تمامیت stage، وابستگی‌ها، baseline و ساختار سرویس را بررسی می‌کند. قدیمی‌بودن Python محیط فعال قرار نیست با pip یا بازسازی درجا رفع شود؛ آن محیط برای backup و rollback حفظ می‌شود.
4. پیش از توقف یا تغییر برنامه، snapshot معتبر app، تنظیمات، venv و SQLite همراه restore-check گرفته می‌شود. پس از توقف مجاز، snapshot SQLite تازه و آزمون مهاجرت روی کپی جدا اجرا می‌شود؛ در این مرحله آزمایش هیچ‌یک روی دیتابیس Production انجام نشده است.
5. app و venv قبلی در backup با نام displaced-app و displaced-venv نگه داشته می‌شوند. /opt/radepa/venv به venv Python 3.10 تأییدشده در مسیر ثابت stage پیوند می‌خورد. خود venv قدیمی تغییر نمی‌کند؛ مسیر ورودی سرویس به محیط جدید اشاره می‌کند. مسیر cache مرورگر جدید نیز در تنظیمات ثبت می‌شود.
6. در شکست نصب، نصب‌کننده کد، تنظیمات و venv قبلی را برمی‌گرداند و راه‌اندازی نسخه قبلی را درخواست می‌کند. SQLite زنده خودکار به گذشته برنمی‌گردد؛ سفارش‌ها و اعتبارهای جدید نباید حذف شوند. فعال‌بودن پردازش به‌تنهایی جای پذیرش کاربردی Telegram را نمی‌گیرد.

برای امکان rollback، binary اصلی Python 3.11.0rc1 سیستم، کتابخانه‌های آن و پوشه backup قدیمی را هم حفظ کنید؛ venv پایتون، interpreter مستقل از سیستم را تضمین نمی‌کند. rollback در این سناریو بازگشت موقت به همان محیط سالم قبلی است، حتی اگر Python آن پیش‌انتشار باشد. قبل از مجوز جایگزینی، هیچ symlink جدیدی روی /opt/radepa/venv نسازید. در برنامه حاضر هیچ دستور نصب، restart یا rollback Production اجرا نمی‌شود.

## نتیجه آزمایش و محدودیت‌ها

در ۲۰۲۶-۱۱-۰۱، همین بسته منتشرشده، بدون تغییر سورس یا وابستگی‌ها، در کانتینر تازه رسمی ubuntu:22.04 اجرا شد. CA معتبر محیط به‌صورت readonly mount و proxy حفظ شد. هیچ bind mount از /opt/radepa یا سرویس Production وجود نداشت.

| بررسی واقعی | نتیجه |
|---|---|
| ZIP d2dfd8b / منشأ سورس 38fd00a | SHA256 برابر `5ff8e812d5c4a2adfdb76d016a41d90dc4b4752252cdd77ccac4f8208e83ec1f`، آزمون ZIP موفق |
| Python جدید | 3.10.12 نهایی؛ venv تازه با /usr/bin/python3.10 ساخته شد |
| وابستگی‌های نصب‌شده | python-telegram-bot=21.5، playwright=1.64.1؛ pip check موفق |
| کل suite بسته در stage مستقل | ۱۳۵ تست، صفر failure و error، یک skip شناخته‌شده به علت نبود Chromium سیستم |
| startup_without_playwright | passed؛ polling شبیه‌سازی‌شده، بدون اتصال Telegram |
| stage بدون مرورگر | موفق، ready.browser=false؛ عمداً غیرقابل نصب |
| کتابخانه‌های Ubuntu برای مرورگر | playwright install-deps chromium موفق |
| stage پیش‌فرض با مرورگر رسمی | exit=1؛ دانلود Chromium revision 1248 / Chrome for Testing 156.0.8078.4 با HTTP 403 و Domain forbidden از cdn.playwright.dev مسدود شد |
| نشانگر مرورگر موفق | ready.json مرحله مرورگر تولید نشد؛ browser=true یا نتیجه مرورگر موفق ساخته نشد |

در نتیجه سازگاری پایتونی بسته با Python 3.10.12 تأیید شد؛ اجرای مرورگر رسمی روی Ubuntu همچنان تأیید نشده است. این شکست در لایه دسترسی دانلود است؛ خطای وابستگی Python یا گزارش crash مرورگر نیست. مرحله بدون مرورگر جایگزین این پذیرش نمی‌شود. تغییر کد ربات، شل‌کردن Preflight یا حذف TLS این مانع را حل نمی‌کند.

گزارش‌های اجرای آزمایشی در محیط کار زیر /workspace/artifacts/python310-staging-20261101 ثبت شدند: runtime.json، offline-health.json، offline-ready.json، pip-check.log، chromium-deps.log، chromium-download-plan.log و browser-install.log. این گزارش‌ها مربوط به کانتینر آزمایش‌اند؛ venv کانتینر با خروج آن حذف شد و نباید stage قابل deploy سرور تلقی شود.

پذیرش نهایی تا فراهم‌شدن دسترسی مجاز دانلود، موفقیت مرورگر رسمی و بررسی شواهد محیط پایدار جدید متوقف می‌ماند. ZIP قبلی و checksum آن تغییر نکردند؛ تغییرات این مرحله فقط مستنداتی‌اند. هیچ Restart، Deploy، Merge، تغییر venv فعال یا دسترسی به SQLite Production انجام نشد.
