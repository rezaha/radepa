# جستجوی رایگان یوزرنیم با Sherlock

این تغییر روی شاخه `feature/sherlock-username-search` و بر پایه کد منوی بومی تلگرام
در `43ca48c` آماده شده است. هیچ نصب، Restart، تغییر دیتابیس یا تماس Telegram روی
Production انجام نشده است. قابلیت به‌صورت پیش‌فرض **غیرفعال** است.

## رفتار و مرز قابلیت

- پس از `/start`، در گفت‌وگوی خصوصی: `/sherlock YOUR_USERNAME` یا `/sherlock @YOUR_USERNAME`.
- دکمه «🔎 جستجوی یوزرنیم در وب» در هر دو منوی اصلی فقط راهنما را نمایش می‌دهد؛
  هیچ حالت انتظار برای دریافت یوزرنیم از پیام عادی ایجاد نمی‌کند. فرمان در Menu بومی هم هست.
- تنها یک نام، حداکثر ۶۴ کاراکتر ASCII، پذیرفته می‌شود: کاراکتر اول حرف، عدد یا زیرخط؛
  بقیه حرف، عدد، زیرخط، نقطه یا خط تیره. URL، ایمیل، آرگومان اضافی و گزینه CLI رد می‌شوند.
- حساب ثبت‌نشده باید `/start` بزند؛ کاربر مسدود اجازه جستجو ندارد. اعتبار ایمیل،
  اینستاگرام و تحلیل کم نمی‌شود؛ schema، سفارش‌ها و سرویس‌های پرداخت تغییر نکرده‌اند.
- پس از پیام «در حال جستجو…»، اجرا با `Application.create_task` در PTB 21.5 دنبال می‌شود.
  ثبت هندلر تازه فقط برای فرمان و callback اختصاصی است. مسیر پیام‌های عادی همان مسیر فعلی است.
- فقط ردیف‌های `Claimed` با لینک HTTP(S) معتبر نمایش داده می‌شوند؛ لینک‌های تکراری حذف
  می‌شوند. حداکثر ۵ لینک در هر پیام و ۵۰ لینک در کل گزارش، همراه اعلام محدودیت، ارسال می‌شود.
  فاصله پیام‌های گزارش یک ثانیه و مهلت کل ارسال گزارش ۳۰ ثانیه است.
- یکسان بودن یوزرنیم **مالکیت مشترک حساب‌ها را ثابت نمی‌کند**. نتیجه Sherlock احتمالی
  است و ممکن است کاتالوگ قدیمی یا روش تشخیص سایت خطا داشته باشد. هیچ داده خصوصی،
  ایمیل/تلفن بازیابی یا ورود به حساب از این مسیر دریافت نمی‌شود.

## اجرای ابزار و تشخیص نتیجه ناقص

بسته رسمی `sherlock-project==0.16.2` یک وابستگی **اختیاری** در
`requirements-sherlock.txt` است؛ requirements اصلی ربات تغییر نکرده است. REST API،
اشتراک یا کلید API لازم نیست. CLI روی همان ماشین و ترجیحاً در venv جدا اجرا می‌شود.
خاموش بودن قابلیت یا نصب نبودن ابزار، import و راه‌اندازی ربات را متوقف نمی‌کند.

سرویس `app/services/sherlock_service.py` بدون shell از
`asyncio.create_subprocess_exec` استفاده می‌کند؛ آرگومان‌ها جدا هستند:

```text
sherlock USERNAME --csv --print-all --local --timeout 10 --folderoutput TEMP_DIRECTORY
```

در نسخه 0.16.2، CSV پیش‌فرض ممکن است فقط یافته‌ها را بنویسد؛ بنابراین `--print-all`
ضروری است. `csv.DictReader` ستون‌های `name`، `url_user`، `exists` و در صورت وجود
`http_status` را می‌خواند. `Available`، `Unknown`، `WAF`، `Illegal` و وضعیت‌های ناشناخته
در نتیجه داخلی حفظ می‌شوند. خطای HTTP، خروج ناموفق، CSV ناقص/خراب یا timeout،
«صفر نتیجه موفق» گزارش نمی‌شوند. خروجی خالی یا بدون ردیف بررسی‌شده نیز شکست است.

`--local` کاتالوگ همراه همان بسته را استفاده می‌کند. خود نسخه رسمی پیش از جستجو
ممکن است نسخه جدید را از GitHub با timeout ده ثانیه بررسی کند؛ این زمان در سقف کل
فرایند حساب می‌شود. ارتباط با سایت‌های عمومی همچنان نیازمند دسترسی خروجی مجاز است.
proxy و تنظیمات اعتماد CA محیط حفظ می‌شوند؛ WAF یا محدودیت سایت دور زده نمی‌شود.

برای هر درخواست یک پوشه موقت جدا ساخته و در پایان، خطا و timeout پاک می‌شود.
stdout/stderr ابزار ذخیره نمی‌شود و کلیدهای شناخته‌شده ربات به فرایند فرزند داده
نمی‌شوند. وضعیت‌های CSV فقط تا ارسال گزارش در حافظه‌اند؛ تاریخچه دائمی تازه‌ای نداریم.
در timeout یا لغو، فرایند و گروه فرایند آن در Ubuntu ابتدا TERM و پس از دو ثانیه KILL
دریافت می‌کنند. ظرفیت تا پایان ارسال گزارش نگه داشته می‌شود؛ صف نامحدود وجود ندارد.
محدودیت‌ها در حافظه همان پردازش هستند و با راه‌اندازی مجدد صفر می‌شوند.

## Python و مسیر محیط مجازی

محیط توسعه این تغییر `/workspace/venvs/radepa` با Python 3.12.14 و PTB 21.5 است.
طبق آخرین خروجی تأییدشده مدیر، مسیر فعال سرور `/opt/radepa/venv/bin/python` به محیط
`/opt/radepa-releases/radepa-q30i0nmv/venv` با Python **3.10.12 پایدار** متصل بوده است.
این اطلاعات از وضعیت قبلی است؛ در این تسک دسترسی زنده SSH یا تغییر سرور نداشته‌ایم.
برای بررسی فقط‌خواندنی روی سرور، بدون نمایش تنظیمات محرمانه:

```bash
systemctl show radepa.service -p WorkingDirectory -p User
readlink -f /opt/radepa/venv
/opt/radepa/venv/bin/python -I -B -c \
  'import sys; from importlib.metadata import version; print(sys.version.split()[0], sys.version_info.releaselevel, sys.prefix, version("python-telegram-bot"))'
```

سازگاری باید با نسخه **پایدار** Python 3.10 و PTB 21.5 بررسی شود؛ محیط قدیمی
3.11.0rc1 را مبنای نصب جدید قرار ندهید. برای Sherlock نیازی به Chromium یا Playwright
نیست؛ قابلیت Inspector موجود وابستگی خودش را حفظ می‌کند.

## نصب و آزمون روی Ubuntu 22.04 آزمایشی

دستورات زیر برای محیط آزمایشی‌اند؛ به `/opt/radepa` یا سرویس فعال دست نمی‌زنند.
وجود Python 3.10 و ماژول venv را بررسی کنید. اگر venv موجود نیست، روی همان محیط
آزمایشی `sudo apt-get install git python3.10-venv ca-certificates` لازم است.

```bash
set -euo pipefail
umask 077
python3.10 -I -B -c \
  'import sys, venv; assert sys.version_info[:2] == (3, 10) and sys.version_info.releaselevel == "final"; print(sys.version.split()[0])'
radepa_test_root=$(mktemp -d "$HOME/radepa-sherlock-test.XXXXXXXX")
git clone --single-branch --branch feature/sherlock-username-search \
  https://github.com/rezaha/radepa.git "$radepa_test_root/repo"
cd "$radepa_test_root/repo/Radepa-Channel-Update/Radepa-server-review"
python3.10 -m venv "$radepa_test_root/bot-venv"
"$radepa_test_root/bot-venv/bin/python" -m pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 "$radepa_test_root/bot-venv/bin/python" \
  -m unittest discover -s tests -q
"$radepa_test_root/bot-venv/bin/python" -m pip check
python3.10 -m venv "$radepa_test_root/sherlock-venv"
"$radepa_test_root/sherlock-venv/bin/python" -m pip install -r requirements-sherlock.txt
"$radepa_test_root/sherlock-venv/bin/python" -m pip check
"$radepa_test_root/sherlock-venv/bin/sherlock" --version
"$radepa_test_root/sherlock-venv/bin/sherlock" --help
printf 'SHERLOCK_BINARY=%s\n' "$radepa_test_root/sherlock-venv/bin/sherlock"
```

`--help` و `--version` جستجوی واقعی انجام نمی‌دهند. نصب اختیاری را در venv فعال ربات
انجام ندهید. خروجی آخر مسیر واقعی باینری برای تنظیمات آزمایش را می‌دهد.
در فایل `.env` **نسخه آزمایشی**، مقادیر زیر را با حفظ تنظیمات دیگر اضافه کنید؛
مسیر نمونه را با همان خروجی واقعی عوض کنید:

```dotenv
SHERLOCK_ENABLED=true
SHERLOCK_BINARY=/absolute/test/path/sherlock-venv/bin/sherlock
SHERLOCK_MAX_CONCURRENT=1
SHERLOCK_SITE_TIMEOUT=10
SHERLOCK_TOTAL_TIMEOUT=120
SHERLOCK_COOLDOWN=60
```

پیش‌فرض `SHERLOCK_ENABLED=false` است. حدود معتبر: تعداد اجرا ۱ تا ۴، timeout هر سایت
۱ تا ۳۰ ثانیه، سقف کل از timeout هر سایت تا ۳۰۰ ثانیه، فاصله درخواست هر کاربر
۱ تا ۳۶۰۰ ثانیه. هر کاربر فقط یک اجرای فعال دارد. تنظیمات در شروع ربات خوانده می‌شوند.

برای پذیرش تعاملی، فقط از **توکن ربات آزمایشی جدا**، `DB_PATH` و `LOG_FILE` آزمایشی
استفاده کنید؛ polling دیگری با توکن Production اجرا نکنید. سپس با مفسر `bot-venv`
و از پوشه همین نسخه آزمایشی، `python -m app.main` را اجرا کنید. آزمون پذیرش:

1. دکمه جدید تنها راهنما بدهد؛ پیام عادی وارد Sherlock نشود.
2. `/sherlock @YOUR_USERNAME` یک جستجوی رایگان و گزارش فارسی بدهد؛ موجودی ثابت بماند.
3. `/sherlock one two` و `/sherlock --help` رد شوند؛ درخواست تکراری محدود شود.
4. با باینری ناموجود، پیام «اجرا نشد» بدهد؛ شکست را نتیجه صفر اعلام نکند.
5. پشتیبانی، رسید عکس، پاسخ ادمین، بررسی ایمیل و تحلیل اینستاگرام را با داده آزمایشی بررسی کنید.

این دستور جستجو به سایت‌های عمومی درخواست واقعی می‌فرستد؛ نتایج و کامل‌شدن آن به
دسترسی شبکه و پاسخ سایت‌ها وابسته است. در این تغییر هیچ جستجوی زنده کاربری انجام نشده است.

## آزمون‌ها و انتشار بعدی

آزمون‌های جدید شامل ورودی نامعتبر، CSV دارای یافته، صفر واقعی، وضعیت‌های نامشخص،
CSV خراب، ابزار غایب/خراب، timeout با کشتن واقعی فرزند آزمایشی، پاک‌سازی پوشه،
سهمیه و هم‌زمانی، مجوز کاربر و ثبت/مسیریابی واقعی PTB با APIهای mock هستند.
کل suite مسیرهای پرداخت، ایمیل، SARPI/تحلیل، Inspector، منو و پشتیبانی را نیز پوشش می‌دهد.
ابزارهای نصب در تست‌ها شبیه‌سازی می‌شوند؛ پیام `INSTALL_OK` در لاگ آزمون، نصب واقعی نیست.

نتیجه واقعی بررسی نهایی در ۲۰۲۶/۱۱/۱۰:

| محیط | نتیجه |
| --- | --- |
| Python 3.12.14، PTB 21.5، محیط توسعه | ۲۲۰ آزمون؛ بدون خطا، شکست یا skip |
| کانتینر مستقل Ubuntu 22.04، Python 3.10.12 پایدار، PTB 21.5 | ۲۲۰ آزمون؛ بدون خطا/شکست، یک skip به علت نبود Chromium سیستم |
| venv جدا با Python 3.10.12 و بسته رسمی PyPI | `Sherlock v0.16.2`؛ help، flags مورد استفاده و کاتالوگ همراه بسته تأیید شد |
| وابستگی‌ها و سورس | `pip check` ربات و ابزار موفق؛ syntax Python 3.10 و `git diff --check` موفق |

۳۱ آزمون جدید به suite قبلی اضافه شده است. بررسی Ubuntu نهایی روی کپی ثابت و فقط‌خواندنی
از سورس اجرا شد. درخواست زنده به سایت‌های پروفایل یا Telegram جزو این نتایج نیست.

فایل‌های تغییرکرده (مسیرها نسبت به همین پوشه `Radepa-server-review`):

| فایل‌ها | تغییر |
| --- | --- |
| `app/services/sherlock_service.py` | سرویس جدید CLI، CSV، محدودیت و پاک‌سازی |
| `app/handlers/sherlock.py` | فرمان، مجوز، task پس‌زمینه و گزارش فارسی |
| `app/config.py`، `app/main.py` | تنظیمات اختیاری، ثبت هندلر و shutdown |
| `app/handlers/start.py`، `app/handlers/breach.py`، `app/utils/keyboards.py` | راهنما، دکمه و حفظ مسیریابی ورودی |
| `app/services/telegram_menu.py` | افزودن فرمان به Menu تلگرام |
| `requirements-sherlock.txt` | پین نسخه ابزار اختیاری |
| `tests/test_sherlock_config.py`، `tests/test_sherlock_service.py`، `tests/test_sherlock_handler.py` | آزمون‌های جدید آفلاین و مسیریابی |
| `tools/build_release.py`، `tools/release_manager.py`، `tests/test_release_manager.py` | همراه‌داشتن requirements اختیاری در بسته با آزمون allowlist |
| `docs/SHERLOCK_FA.md` | نصب آزمایشی، تنظیمات، پذیرش و نتیجه آزمون‌ها |

برای انتشار آتی، بسته و baseline نصب‌کننده باید جداگانه تأیید شوند. نصب‌کننده‌های تاریخی
`install_telegram_menu.py` و `install_support_replies.py` به fingerprint قدیمی بسته‌اند؛
از آن‌ها برای نصب این app جدید استفاده نکنید و guard را تغییر ندهید. فقط allowlist
ساخت/اعتبارسنجی بسته برای همراه‌داشتن فایل اختیاری requirements گسترش یافته است؛
ZIP تاریخی دوباره ساخته نشده است. shutdown در PTB منتظر taskهای ثبت‌شده می‌ماند؛
در انتشار آتی، مهلت systemd باید سقف اجرا + توقف فرزند + ارسال گزارش را پوشش دهد.
این مرحله هیچ دستور Deploy، Restart یا Merge ندارد.

در checkout فعلی `AGENTS.md` و فایل دقیق `Radepa-Project-Handoff-FA.md` وجود نداشتند؛
سورس فعلی و راهنمای قدیمی‌تر `Radepa-Codex-Handoff-2026-10-25(1).md` در ریشه مخزن
برای شناخت ساختار و قواعد حفاظت از تنظیمات/داده‌ها بررسی شدند.
