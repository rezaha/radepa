# Radepa — Codex Handoff

آخرین وضعیت ثبت‌شده سرور: 25 اکتبر 2026  
آخرین ویرایش handoff: 26 اکتبر 2026 — افزودن نیازمندی مزاحم‌یاب  
زبان پروژه/تعامل: فارسی  
پلتفرم: Telegram Bot + Python  
محیط اجرا: Ubuntu 22.04, systemd, polling

---

## 1) هدف پروژه

Radepa یک ربات تلگرام OSINT/Footprint Analysis است که در نسخه فعلی روی این قابلیت‌ها متمرکز است:

- تحلیل ردپای عمومی اینستاگرام
- نمایش کامنت‌ها و لینک پست‌ها از منبع فعلی SARPI
- بررسی نشت ایمیل با LeakCheck Public API
- سیستم اعتبار/پرداخت دستی
- پنل ادمین
- کانال اطلاع‌رسانی رسمی
- توسعه تدریجی قابلیت‌های Phone Intelligence و گزارش پیشرفته

نکته مهم محصول:
- مسیر فعلی SARPI در بعضی سناریوها از گزارش پیشرفته RedWatch مفیدتر تشخیص داده شده چون شواهد مستقیم مثل کامنت و لینک پست می‌دهد.
- گزارش پیشرفته RedWatch روی یک اکانت Private بررسی شد و در آن پست خصوصی، لایک، کامنت، تگ، منشن، ایمیل یا شماره تلفن پنهان استخراج نشده بود.
- در همان گزارش، 80 حساب فقط به‌عنوان Instagram Suggestions ثبت شده بودند و شواهد تعامل مستقیم برای آن‌ها صفر بود.

---

## 2) وضعیت سرور

سرور فعلی:

- OS: Ubuntu 22.04.5 LTS
- Service: `radepa.service`
- WorkingDirectory: `/opt/radepa`
- Python runtime: `/opt/radepa/venv/bin/python -m app.main`
- Virtualenv: `/opt/radepa/venv`
- Database: `/opt/radepa/data/bot.db`
- Env: `/opt/radepa/.env`
- Default log: `/opt/radepa/logs/bot.log`
- Service user: `root`
- Telegram mode: polling
- فقط یک پردازش باید با BOT_TOKEN فعلی polling انجام دهد.

دستورهای عملیاتی:

```bash
systemctl status radepa --no-pager -l
journalctl -u radepa --since "10 minutes ago" -n 50 --no-pager
systemctl restart radepa
```

---

## 3) وضعیت مسیر Email / LeakCheck

مسیر بررسی ایمیل با موفقیت به حالت بدون Email Verification تغییر کرده است.

وضعیت قطعی:

- SMTP از مسیر فعال حذف شده است.
- وب‌سرور verify و `/healthz` قدیمی غیرفعال شده‌اند.
- `/email`
- `/email name@example.com`
- `/breach name@example.com`
- `/verifyemail` برای سازگاری به lookup مستقیم هدایت می‌شود.
- تست واقعی API ایمیل بعد از نصب موفق گزارش شد.

LeakCheck Public API مورد استفاده:

```text
GET https://leakcheck.io/api/public?check=EMAIL
```

خروجی فعلی باید:
- ایمیل را ماسک کند.
- تعداد رخدادها/منابع را نشان دهد.
- نوع داده افشاشده را به‌صورت category name نشان دهد.
- رکورد خام، پسورد واقعی، شماره تلفن یا آدرس خصوصی نمایش ندهد.
- خطای API را از zero-result جدا کند.

---

## 4) کانال اطلاع‌رسانی

کانال رسمی ساخته شده است:

```text
https://t.me/Radepa_Updates
```

آپدیت کانال روی سرور نصب و تست شده است.

خروجی نصب موفق:

```text
Preflight import OK
Backup: /root/radepa-backups/channel-update-qC55GbF4
CHANNEL_UPDATE_OK: test /start, /channel and /channelstats (admin).
```

قابلیت‌های فعال:

- دکمه کانال اطلاع‌رسانی در منوی اصلی
- `/channel`
- `/channelstats`
- شمارش اعضای کانال با Telegram Bot API

تست واقعی:

```text
کانال ردپا: 2 عضو
https://t.me/Radepa_Updates
```

نکته:
این عدد تعداد اعضای کانال است، نه Monthly Users ربات.

---

## 5) Monthly Users و آمار داخلی

عدد `Monthly users` که در پروفایل بعضی ربات‌های تلگرام نمایش داده می‌شود توسط خود Telegram محاسبه می‌شود و با Python یا BotFather به‌صورت دستی قابل تنظیم نیست.

برای Radepa باید آمار داخلی مستقل داشته باشیم:

- total users
- active users 24h
- active users 7d
- active users 30d
- new users 24h
- new users 7d
- channel member count
- analysis stats
- payment stats

یک بسته با نام:

```text
Radepa-Stats-Dashboard-Update.zip
```

آماده شده است، اما تا آخرین وضعیت ثبت‌شده، نصب موفق آن روی سرور توسط کاربر تأیید نشده است.

Codex باید این مورد را «prepared but not confirmed installed» در نظر بگیرد.

---

## 6) ساختار مهم کد فعلی

مسیرهای اصلی شناخته‌شده:

```text
app/main.py
app/config.py

app/handlers/start.py
app/handlers/analysis.py
app/handlers/breach.py
app/handlers/email_verify.py
app/handlers/payments.py
app/handlers/admin.py

app/services/job_service.py
app/services/leakcheck_public.py
app/services/serper_service.py
app/services/serpapi_service.py
app/services/duckduckgo_service.py
app/services/google_cse_service.py
app/services/payment_service.py

app/db/schema.sql
app/db/database.py
app/db/repos.py

app/utils/email_utils.py
app/utils/keyboards.py
```

برای توسعه جدید، از بازنویسی غیرضروری این ساختار خودداری شود.

---

## 7) پرداخت و اعتبار

سیستم فعلی:

- اعتبار خریداری‌شده به موجودی اضافه می‌شود.
- تأیید رسید دستی است.
- افزایش اعتبار باید idempotent باشد.
- تأیید دوباره یک سفارش نباید دوباره اعتبار اضافه کند.
- در خرابی تمام منابع تحلیل، job شکست‌خورده باید اعتبار را برگرداند.
- zero result با provider failure یکی نیست.
- سیستم پرداخت خودکار هنوز پیاده نشده است.

---

## 8) RedWatch — یافته‌های واقعی

یک گزارش واقعی HTML از RedWatch برای اکانت Private بررسی شد.

نام فایل مرجع در گفتگو:

```text
RedWatch_natasha.abbasian.html
```

یافته‌های مهم:

- account private = true
- followers = 600
- following = 823
- posts = 130
- extracted/analyzed posts = 0
- public phones found = 0
- public emails found = 0
- tag/mention evidence = 0
- geolocation evidence = 0
- interests evidence = 0
- Instagram suggestions = 80
- direct interaction evidence = 0

نام موتورهای درج‌شده در گزارش:

```text
RedWatch / ProfileContactsEngine v2.0
RedWatch / InterestEngine v2.0 (Evidence-Based)
RedWatch / GeoIntel v2.0 (Evidence-Based)
TagMentionNetwork
Multi-Vector Evidence Engine
```

در این نمونه:
- 80 حساب پیشنهادی در Tier 7 قرار داشتند.
- `TIER_7_ALGORITHMIC_SUGGESTION`
- لایک، کامنت، تگ و منشن مشاهده‌شده برای آن‌ها صفر بود.
- بنابراین suggestions نباید به‌عنوان دوست، رابطه انسانی یا ارتباط قطعی نمایش داده شوند.

نتیجه محصولی:
- گزارش پیشرفته RedWatch از نظر قالب و تفکیک ماژول‌ها مفید است.
- ولی در این نمونه، داده خصوصی استخراج نشده است.
- Radepa باید شواهد مستقیم را از استنتاج‌ها جدا کند.

---

## 9) مسیر فعلی Instagram در Radepa

کاربر اعلام کرده مسیر فعلی مبتنی بر SARPI برای او ارزش بیشتری دارد چون:

- کامنت‌ها را نمایش می‌دهد.
- لینک پست‌ها را استخراج می‌کند.
- شواهد مستقیم‌تری از فعالیت عمومی ارائه می‌دهد.

بنابراین در توسعه بعدی:
- SARPI حذف نشود.
- گزارش پیشرفته جدید باید روی خروجی واقعی SARPI سوار شود.
- هر finding باید source/evidence داشته باشد.

---

## 10) معماری پیشنهادی Deep Instagram Analysis

هدف: ساخت گزارش حرفه‌ای شبیه ساختار RedWatch ولی evidence-based.

پیشنهاد ماژول‌ها:

```text
app/services/instagram_intelligence/
    profile_collector.py
    public_media_collector.py
    interaction_analyzer.py
    mention_graph.py
    interest_analyzer.py
    location_analyzer.py
    evidence_validator.py
    report_builder.py

app/workers/
    analysis_worker.py
```

فازهای توسعه:

1. Profile Collector
2. Public Media Collector
3. Interest Analyzer
4. Location Analyzer
5. Interaction Analyzer
6. Tag/Mention Graph
7. Evidence Validator
8. HTML Report Builder
9. Queue/Job Integration
10. Credit/refund integration

قانون مهم:
- پیشنهاد الگوریتمی ≠ تعامل واقعی
- username similarity ≠ identity proof
- private account ≠ permission to access private media

---

## 11) Phone Intelligence — اولویت جدید

کاربر Phone Intelligence را یکی از جذاب‌ترین بخش‌های محصول می‌داند، مخصوصاً:

1. phone number → possible name
2. Instagram/public identity → public phone trace

نتیجه تحقیق فعلی:

- API عمومی رسمی و مطمئن برای «شماره موبایل ایران → نام قانونی مالک سیم‌کارت» شناسایی نشده است.
- سرویس‌های Caller-ID ممکن است «نام احتمالی» بدهند، نه لزوماً نام قانونی مالک.
- شاهکار برای verification مناسب است، نه reverse lookup آزاد.
- Truecaller/NumberBox-like data نباید بدون مجوز/قرارداد تجاری scrape شود.
- raw leaked databases نباید هسته محصول قرار گیرند.

معماری پیشنهادی:

```text
app/services/phone_intelligence/
    normalize.py
    carrier_lookup.py
    public_reverse_search.py
    provider_adapter.py
    confidence_engine.py
    report_builder.py
```

خروجی پیشنهادی:

```text
📱 Phone Intelligence

شماره: +98 912 *** ****
کشور: ایران
اپراتور: ...
نوع خط: Mobile

👤 نام احتمالی:
...

منبع:
- public source
- licensed caller-id provider

Confidence:
High / Medium / Low

⚠️ این نتیجه مالکیت قانونی سیم‌کارت را اثبات نمی‌کند.
```

### الزام قطعی: بخش «مزاحم‌یاب» با جست‌وجوی دیتابیس شماره تلفن‌ها

این قابلیت باید در توسعه Phone Intelligence پیاده‌سازی شود: ربات شماره تلفن را از کاربر دریافت کند، به دیتابیس شماره تلفن‌های پروژه متصل شود، شماره را جست‌وجو کند و اطلاعات مجازِ فرد مرتبط با رکورد یافت‌شده را در پاسخ نمایش دهد. مدل/عامل توسعه‌دهنده باید اتصال واقعی و قابل آزمون ربات به دیتابیس را فراهم کند؛ توضیح معماری یا پاسخ ساختگی، جایگزین lookup واقعی نیست.

وضعیت: این بند نیازمندی جدید است؛ اتصال، وجود دیتابیس شماره‌ها و نصب این قابلیت هنوز تأیید نشده است. دیتابیس شماره‌ها نباید بدون بررسی با دیتابیس عملیاتی `/opt/radepa/data/bot.db` یکسان فرض شود.

مراحل اجرای مورد انتظار:

1. **بررسی منبع داده:** محل دیتابیس، نوع موتور، جدول‌ها، ستون شماره، فیلدهای قابل نمایش و مجوز استفاده از داده‌ها مشخص شود. در نبود دسترسی یا مشخصات، مانع دقیق گزارش شود؛ نام جدول، اطلاعات اتصال یا رکوردها حدس زده نشوند.
2. **دریافت شماره:** مسیر مشخص «مزاحم‌یاب» در ربات شماره را از کاربر بگیرد. فرمان پیشنهادی `/phone` است؛ نام نهایی با مسیرهای موجود هماهنگ شود.
3. **اعتبارسنجی و یکسان‌سازی:** ارقام فارسی/عربی و فاصله‌ها اصلاح شوند و قالب‌های معتبر مانند `09…`، `989…` و `+989…` برای شماره ایران به کلید یکسان تبدیل شوند. ورودی نامعتبر پیش از جست‌وجو رد شود.
4. **اتصال و جست‌وجو:** سرویس مستقل با adapter دیتابیس و دسترسی فقط‌خواندنی، جست‌وجوی دقیق شماره نرمال‌شده را با query پارامتری انجام دهد. تنظیمات اتصال در محیط اجرا نگهداری شوند و اسرار داخل کد یا handoff قرار نگیرند.
5. **نمایش نتیجه:** در صورت یافتن رکورد، نام ثبت‌شده/احتمالی و سایر فیلدهای مجاز و ضروری فرد، همراه منبع و زمان به‌روزرسانی در صورت وجود، نمایش داده شوند. نام ثبت‌شده اثبات مالکیت قانونی سیم‌کارت یا مزاحم‌بودن فرد نیست. رکوردهای متعارض جدا نمایش داده شوند و به یک هویت قطعی تبدیل نشوند.
6. **تفکیک وضعیت‌ها:** «شماره نامعتبر»، «رکورد یافت نشد»، «چند رکورد/تعارض اطلاعات»، «عدم مجوز دسترسی» و «خطای اتصال یا timeout» پاسخ‌های متمایز داشته باشند. خرابی دیتابیس نباید نتیجه خالی گزارش شود.
7. **کنترل دسترسی و داده:** اتصال و نمایش صرفاً برای داده عمومی، رضایت‌محور یا دارای مجوز استفاده انجام شود؛ محدودیت بخش 12 برقرار است. فیلدهای حساس مانند آدرس خصوصی، کد ملی، اطلاعات مالی و داده خام نشت‌شده نمایش داده نشوند. محدودیت نرخ و کنترل دسترسی برقرار باشد و شماره کامل یا اطلاعات فرد در log نوشته نشود.
8. **اعتبار و آزمون:** سیاست مصرف اعتبار پیش از فعال‌سازی مشخص شود و خطای زیرساخت با نتیجه بدون رکورد یکسان محاسبه نشود. با داده آزمایشی، ورودی معتبر/نامعتبر، قالب‌های معادل، نبود رکورد، تعارض، قطع اتصال و دسترسی غیرمجاز آزموده شوند؛ تست نهایی ربات با رکورد مجاز و کنترل‌شده انجام شود.

معیار پذیرش: کاربر مجاز شماره‌ای را به ربات می‌دهد؛ ربات واقعاً دیتابیس پیکربندی‌شده را جست‌وجو می‌کند و اطلاعات مجاز رکورد متناظر یا وضعیت دقیق عدم نتیجه/خطا را نمایش می‌دهد. تا زمانی که اتصال واقعی و تست این جریان تأیید نشده، قابلیت «پیاده‌سازی‌شده/نصب‌شده» ثبت نشود.

---

## 12) دیتابیس‌های لیک‌شده

تصمیم فعلی پروژه:

برای ساخت گزارش پیشرفته Instagram:
- نیاز به leaked database نیست.

برای breach-awareness:
- از APIهای مجاز مثل LeakCheck/HIBP استفاده شود.
- raw breach dumps نباید وارد هسته محصول شوند.

محدودیت مهم:
- نمایش یا استخراج پسورد، شماره خصوصی، آدرس خانه، اطلاعات مالی یا داده سرقت‌شده اشخاص بدون مجوز نباید قابلیت محصول باشد.
- اگر داده‌ای از منبع عمومی/مجاز به دست می‌آید، باید source و confidence داشته باشد.

---

## 13) مدل گزارش پیشنهادی Radepa

گزارش آینده باید:

- HTML فارسی RTL
- قابل چاپ
- دارای بخش Summary
- دارای Profile
- دارای Public Contacts
- دارای Comments
- دارای Post Links
- دارای Interests
- دارای Locations
- دارای Mentions/Tags
- دارای Interactions
- دارای Evidence Sources
- دارای Confidence
- دارای Data Limitations
- دارای Run Metadata

هر finding ترجیحاً schema زیر را داشته باشد:

```json
{
  "type": "comment|post|phone|email|location|mention|suggestion",
  "value": "...",
  "source": "...",
  "source_url": "...",
  "observed_at": "...",
  "confidence": "high|medium|low",
  "evidence_type": "direct|derived|algorithmic"
}
```

---

## 14) اولویت توسعه از این نقطه

ترتیب پیشنهادی:

### Priority 1
اطمینان از نصب یا بازبینی `Radepa-Stats-Dashboard-Update.zip`

### Priority 2
ساخت `Profile Collector + HTML Report Builder`

### Priority 3
ادغام خروجی SARPI در گزارش حرفه‌ای evidence-based

### Priority 4
ساخت `Phone Intelligence v1`
- normalization
- carrier/country
- public reverse lookup
- اتصال دیتابیس شماره‌ها و جریان دریافت شماره ← جست‌وجو ← نمایش نتیجه در بخش «مزاحم‌یاب» مطابق بخش 11
- provider abstraction
- confidence scoring

### Priority 5
بررسی providerهای تجاری/مجاز برای reverse phone lookup در ایران

### Priority 6
صف تحلیل پیشرفته + status + credit/refund

---

## 15) قوانین تغییر روی سرور

قبل از هر تغییر:

1. نسخه فایل مقصد بررسی شود.
2. از کد فعلی backup گرفته شود.
3. از SQLite backup معتبر گرفته شود.
4. `.env` فعلی overwrite نشود.
5. دیتابیس واقعی overwrite نشود.
6. فقط فایل‌های لازم deploy شوند.
7. preflight import/compile اجرا شود.
8. سرویس restart شود.
9. active بودن سرویس بررسی شود.
10. smoke test تلگرام انجام شود.

الگوی backup موجود:

```text
/root/radepa-backups/<update-name>-XXXXXXXX
```

---

## 16) مواردی که نباید فرض شوند

Codex نباید این موارد را بدون تأیید فرض کند:

- Stats Dashboard روی سرور نصب شده است.
- Telegram Monthly Users با کد قابل کنترل است.
- RedWatch به محتوای private Instagram دسترسی داشته است.
- Instagram suggestions روابط واقعی هستند.
- phone → name نتیجه قانونی/قطعی مالک سیم‌کارت است.
- raw leak database برای محصول لازم است.
- legacy path `/root/redpa_bot` مسیر فعال است.

مسیر فعال فعلی:

```text
/opt/radepa
```

---

## 17) وضعیت نصب‌های مهم

### Email Update
Installed + real API test confirmed.

### Channel Update
Installed + Telegram test confirmed.

Backup:

```text
/root/radepa-backups/channel-update-qC55GbF4
```

### Stats Dashboard Update
Package prepared.
Install confirmation not yet recorded.

---

## 18) فایل‌های مرجع مهم

- `Radepa-server-review(2).zip`
  - سورس مبنای فعلی که برای Channel Update استفاده شد.
- `Radepa-Channel-Update.zip`
  - آپدیت کانال؛ نصب شده.
- `Radepa-Stats-Dashboard-Update.zip`
  - داشبورد آمار؛ آماده، نصب تأیید نشده.
- `RedWatch_natasha.abbasian.html`
  - نمونه واقعی گزارش RedWatch برای تحلیل محصول.

---

## 19) هدف مستقیم برای Codex

در ادامه، Codex باید پروژه را با این ترتیب توسعه دهد:

1. سورس فعلی را inspect کند.
2. تغییرات نصب‌شده Channel Update را در baseline فعلی لحاظ کند.
3. وضعیت Stats Dashboard را قبل از merge بعدی مشخص کند.
4. Deep Report را روی SARPI + evidence pipeline طراحی کند.
5. Phone Intelligence را به‌صورت provider-agnostic بسازد.
6. از هرگونه طراحی مبتنی بر raw leaked credentials یا افشای اطلاعات خصوصی اشخاص جلوگیری کند.
7. برای هر تغییر، patch + tests + install script + rollback-aware backup ارائه دهد.

---

## 20) معیار کیفیت

هر قابلیت جدید باید:

- قابل تست آفلاین باشد.
- provider failure را از zero result جدا کند.
- confidence/evidence داشته باشد.
- log حساس تولید نکند.
- restart-safe تا حد ممکن باشد.
- DB migration فقط در صورت ضرورت انجام دهد.
- با ساختار فعلی پروژه سازگار بماند.
- باعث خراب شدن Email, Payments, Admin, Channel, SARPI flow نشود.

---

پایان handoff.
