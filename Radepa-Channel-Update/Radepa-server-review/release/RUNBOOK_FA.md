# انتشار شاخه Instagram Inspector — Ubuntu 22.04

**به‌روزرسانی وضعیت:** نصب بعداً با تأیید مدیر انجام و پذیرش اولیه گزارش شد؛ [ثبت نصب و محدودیت 403](DEPLOYMENT_ACCEPTANCE_FA.md) وضعیت جدید را شرح می‌دهد. عبارت‌های «اجرا نشده» پایین مربوط به زمان نگارش راهنمای آماده‌سازی‌اند. این راهنما مجوز نصب مجدد نیست.

این بسته صرفاً آماده انتشار است. در این کار هیچ تغییری روی سرور اصلی اجرا نشده و PR merge نشده است. فایل PR_FILE_MAP_FA.md تفکیک همان ۴۷ فایل اولیه را نشان می‌دهد. این انتشار ابزارهای release و وابستگی صریح tzdata را نیز اضافه می‌کند.

برای مرحله فعلی پذیرش، ابتدا [Preflight فقط‌خواندنی](PREFLIGHT_READONLY_FA.md) و سپس [پذیرش staging روی VM مستقل](STAGING_ACCEPTANCE_FA.md) را دنبال کنید. بخش‌های نصب Production و rollback پایین صرفاً مرجع آینده‌اند؛ در مرحله پذیرش هیچ deploy، restart یا rollback اجرا نشود. ZIP منتشرشده در d2dfd8b ثابت است و مستندات تکمیلی پذیرش بعداً به شاخه اضافه شده‌اند.

## محتوا و اصالت

tools/build_release.py از سورس commit‌شده و پاک، ZIP، SHA256 و manifest شامل هش تک‌تک فایل‌ها می‌سازد. تنها فایل‌های tracked برنامه، تست، ابزار و مستندات بسته‌بندی می‌شوند؛ .env، دیتابیس، venv، cache و فایل untracked وارد بسته نمی‌شوند. manifest فقط کنترل تمامیت است، نه امضای ناشر؛ checksum ZIP را از کانال مورد اعتماد دریافت و پیش از استخراج تطبیق دهید. GitHub archive عادی manifest این بسته را ندارد و مستقیماً ورودی release_manager نیست.

```bash
python3 tools/build_release.py --output /tmp/radepa-inspector-release.zip
```

کنار ZIP، فایل `.zip.sha256` ساخته می‌شود. source_commit در manifest به commit دقیق منشأ اشاره دارد. ابزارهای قدیمی install-email-update.sh، install_single_search.py و install_receipt_review.py برای این انتشار مرورگر مناسب نیستند.

## پیش‌نیاز Ubuntu

Python 3.10 یا بالاتر، python3-venv و کتابخانه‌های Chromium لازم‌اند. روی staging Ubuntu و با مجوز مدیر سیستم، وابستگی‌های سیستم را پیش از ساخت مرحله آماده کنید:

```bash
python3 -m venv /tmp/radepa-browser-setup
/tmp/radepa-browser-setup/bin/python -m pip install playwright==1.64.1
/tmp/radepa-browser-setup/bin/python -m playwright install-deps chromium
```

این فرمان apt و کتابخانه‌های سیستم را تغییر می‌دهد؛ روی Production در این بررسی اجرا نشده است. اگر می‌خواهید حتی تغییر بسته‌های سیستم هم از Production جدا بماند، مرحله تأیید اولیه را روی ماشین یا کانتینر Ubuntu مجزا اجرا کنید. بسته مرورگر در مرحله بعد برای همین نسخه Playwright دانلود می‌شود؛ از دانلود با TLS غیرفعال استفاده نکنید. دسترسی به PyPI و CDN رسمی Playwright و مقصدهای redirect آن لازم است. مسدود بودن CDN باید در تنظیمات شبکه حل شود؛ با host network، حذف پراکسی یا غیرفعال کردن TLS دور زده نشود.

## staging بدون تداخل

پس از استخراج ZIP، از پوشه radepa-release اجرا کنید:

```bash
python3 tools/release_manager.py stage --source "$PWD" --root /opt/radepa-releases
```

این فرمان زیر root انتخابی یک پوشه یکتا می‌سازد، سورس را از manifest تأیید می‌کند، venv و browser cache جدا می‌سازد، pip check، کل تست‌ها و smoke مرورگر روی HTTP fixture محلی را اجرا می‌کند. توکن و کلیدهای واقعی وارد subprocess تست نمی‌شوند؛ تنظیمات ساختگی جایگزین می‌شوند. SQLite و لاگ مستقل داخل state قرار می‌گیرند. app.main با run_polling شبیه‌سازی‌شده راه‌اندازی می‌شود؛ هیچ bot test یا production به Telegram polling متصل نمی‌شود. این یک staging آفلاین برای Application و مرورگر است، نه تست تعاملی Telegram با حساب واقعی.

در خروجی STAGE_READY مسیر مرحله نوشته می‌شود. ready.json به manifest، fingerprint برنامه و pip freeze همان venv متصل است. health.json تعداد تست‌ها، خطاها و skip را نگه می‌دارد. لاگ‌های مرحله فقط برای مالک پوشه قابل دسترسی‌اند؛ قبل از اشتراک‌گذاری، آن‌ها را از نظر اطلاعات حساس بررسی کنید.

برای تشخیص محدود بدون دانلود مرورگر:

```bash
python3 tools/release_manager.py stage --source "$PWD" --root /tmp/radepa-staging --without-browser
```

این مرحله هرگز قابل deploy نیست؛ نبود browser health check مانع نصب است. وجود یک skip در تست browser محلی با نبود system chromium ثبت می‌شود؛ smoke مستقل bundled Chromium باید جدا موفق شود تا ready قابل deploy باشد.

## برنامه نصب بدون اعمال تغییر

```bash
python3 tools/release_manager.py deploy --stage /opt/radepa-releases/RADEPA_STAGE
```

بدون --apply فقط تمامیت staging و ثابت ماندن وابستگی‌ها بررسی می‌شود. نه service متوقف می‌شود و نه backup یا تغییر فایل Production انجام می‌شود. مسیر root staging نباید با /opt/radepa هم‌پوشانی داشته باشد. مراحل داخل /tmp برای Production قابل deploy نیستند، چون ممکن است پاک شوند.

## اعمال نصب در آینده، پس از تأیید انتشار

دستور زیر در این کار اجرا نشده است و فقط برای زمانی است که نصب Production مجاز شود:

```bash
sudo python3 tools/release_manager.py deploy --stage /opt/radepa-releases/RADEPA_STAGE --apply
```

نصب‌کننده فقط ساختار شناخته‌شده /opt/radepa، کاربر سرویس root و ExecStart شامل /opt/radepa/venv/bin/python و app.main را می‌پذیرد. نسخه‌های مبنای شناخته‌شده کد 3ea86bb، نسخه رسید و 17ca5cb هستند. در صورت drift، تغییر کاربر، تغییر unit یا تنظیم browser path در محیط سرویس، پیش از نصب متوقف می‌شود. برای کاربر سرویس غیر root یا ساختار سفارشی باید بسته بازبینی شود.

قبل از هر تغییر در کد، تنظیمات، venv یا توقف سرویس، backup کامل app، .env، requirements، venv، متن unit، فهرست packages و SQLite در مسیر خصوصی /root/radepa-backups/inspector-* ساخته می‌شود. کد و تنظیمات با هش، venv با pip check و SQLite با integrity_check و بازیابی روی فایل جدا بررسی می‌شوند. کمبود فضا باعث توقف می‌شود. پس از توقف سرویس، SQLite دوباره backup و restore-check می‌شود تا آخرین تراکنش‌ها هم حفظ شوند.

مهاجرت ابتدا روی کپی restore و با تنظیم DB_PATH و LOG_FILE جدا، بدون polling اجرا می‌شود. سپس app جدید کپی و venv قدیمی حفظ می‌شود؛ مسیر /opt/radepa/venv به venv ثابت و آزمایش‌شده مرحله symlink می‌شود. فقط تنظیم غیرمحرمانه PLAYWRIGHT_BROWSERS_PATH به .env افزوده می‌شود؛ سایر کلیدها حفظ می‌شوند و unit عوض نمی‌شود. deployment.json مراحل را ثبت می‌کند. قفل فایل مانع نصب و rollback هم‌زمان است.

پوشه release فعال زیر /opt/radepa-releases را حذف یا جابه‌جا نکنید؛ venv و مرورگر سرویس از آن استفاده می‌کنند. INSTALL_OK صرفاً فعال بودن پردازش را تأیید می‌کند. تست واقعی /start، پرداخت آزمایشی، ایمیل، پنل ادمین و /instagram (فقط صفحه ثابت، بدون ورودی) در مرحله پذیرش انتشار لازم است. دسترسی واقعی Instagram ممکن است با policy، redirect یا challenge محدود شود.

## rollback و بازیابی

شکست نصب باعث توقف نسخه جدید، بازگرداندن app، venv و تنظیمات قبلی و راه‌اندازی همان سرویس می‌شود. کد شکست‌خورده و venv جابه‌جا‌شده در backup حفظ می‌شوند. دیتابیس زنده خودکار عقب برنمی‌گردد؛ تراکنش‌های جدید نباید حذف شوند. schema فعلی افزایشی و با نسخه‌های مبنای پشتیبانی‌شده سازگار است.

برای rollback مستقل یا بازیابی نصب نیمه‌تمام، با مسیر واقعی backup:

```bash
sudo python3 tools/release_manager.py rollback --backup /root/radepa-backups/inspector-BACKUP_ID
```

ابتدا اعتبار کد backup و اینکه نسخه دیگری بعداً منتشر نشده بررسی می‌شود. با سرویس خاموش، از SQLite فعلی نیز backup تازه گرفته می‌شود؛ سپس کد و محیط قبلی برمی‌گردند و داده جاری حفظ می‌شود. حالت installing در deployment.json اجازه بازیابی copy نیمه‌تمام را می‌دهد. backup قدیمی را روی انتشار جدیدتر به‌اجبار اعمال نکنید.

اگر خرابی واقعی یا مهاجرت ناسازگار، بازگرداندن دیتابیس را ضروری کرد، این کار جدا و با پذیرش از دست رفتن تراکنش‌های بعد از backup انجام شود: تمام پردازش‌های متصل به DB را متوقف کنید، از وضعیت فعلی با SQLite backup نسخه بگیرید، integrity_check نسخه منتخب و تست restore را تکرار کنید و سپس با API backup خود SQLite آن را به اتصال writable دیتابیس اصلی برگردانید. فایل WAL را هنگام فعال بودن اتصال دستی حذف یا جایگزین نکنید. این انتشار هیچ فرمان خودکار restore-db ندارد.

## محدودیت‌های تأیید

گزارش اجرای واقعی در VALIDATION_FA.md ثبت می‌شود. دسترسی مستقیم به فایل‌های فعلی سرور، نتیجه Telegram واقعی و وضعیت حساب‌های API از این محیط تأیید نشده‌اند. موفقیت تست‌های آفلاین و مرورگر محلی، تأیید رفتار زنده اینستاگرام نیست.
