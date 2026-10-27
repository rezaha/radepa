# نصب نسخه بررسی ایمیل و AbstractAPI روی سرور

این راهنما برای نصب فعلی `/opt/radepa` و `radepa.service` است. روی سرور اجرا
نشده است. ابتدا اتصال واقعی AbstractAPI و ساختار پاسخ آن را تأیید کنید.
اسکریپت قدیمی `install-email-update.sh` و manifest آن برای این نسخه نیستند؛
از آنها برای نصب تغییرات AbstractAPI یا تغییرات خرید تک‌جست‌وجو استفاده نکنید.

## آماده‌سازی در مسیر جدا

با حساب مجاز سرور، شاخه را در مسیری جدا دریافت کنید؛ نصب فعال را با git reset
یا pull بازنویسی نکنید. فرمان‌های زیر نصب روی سرور هستند، نه محیط cloud:

```bash
sudo -i
set -euo pipefail
umask 077
git clone --single-branch --branch codex/single-search-payments-20261026 \
  https://github.com/rezaha/radepa.git /opt/radepa-stage-abstract
cd /opt/radepa-stage-abstract/Radepa-Channel-Update/Radepa-server-review
git rev-parse HEAD
python3 -m venv /opt/radepa-abstract-venv
/opt/radepa-abstract-venv/bin/python -m pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 /opt/radepa-abstract-venv/bin/python -m unittest discover -s tests -v
/opt/radepa-abstract-venv/bin/python -m pip check
```

SHA را با commit تأییدشده مخزن تطبیق دهید. نسخه Python 3.12 آزمایش شده است.
پیش از ادامه، تغییرات `app/`، `requirements.txt` و schema را با نصب فعال مقایسه
کنید؛ تغییرات مستقل سرور باید جداگانه ادغام شوند. این شاخه شامل تغییرات قبلی
اعتبار و پرداخت هم هست؛ فقط سه فایل ایمیل را روی نسخه قدیمی کپی نکنید.

## تنظیمات و پشتیبان‌گیری

WorkingDirectory و ExecStart سرویس، کاربر سرویس و مسیر واقعی DB_PATH و LOG_FILE
را به‌صورت محلی بررسی کنید؛ محتوای `.env` و خروجی حاوی کلید را منتشر نکنید.
فرمان‌های زیر فرض می‌کنند دیتابیس واقعی `/opt/radepa/data/bot.db` است؛ اگر
DB_PATH فرق دارد، همه مسیرهای backup و rollback را قبل از اجرا اصلاح کنید.

سرویس را متوقف کنید تا backup کد و دیتابیس متعلق به یک نقطه زمانی باشد. تا
پایان نصب و تست، هیچ polling process دیگری با همین توکن اجرا نکنید.

```bash
systemctl stop radepa.service
backup_dir=$(mktemp -d /root/radepa-backup-abstract-XXXXXXXX)
chmod 700 "$backup_dir"
cp -a /opt/radepa/app "$backup_dir/app"
cp -p /opt/radepa/.env /opt/radepa/requirements.txt "$backup_dir/"
cp -a /opt/radepa/venv "$backup_dir/venv"
systemctl cat radepa.service > "$backup_dir/radepa.service.txt"
/opt/radepa/venv/bin/python -m pip freeze > "$backup_dir/packages.txt"
/opt/radepa/venv/bin/python - "$backup_dir" <<'PY'
import sqlite3, sys
from pathlib import Path
backup = Path(sys.argv[1])
with sqlite3.connect('/opt/radepa/data/bot.db') as source:
    with sqlite3.connect(backup / 'bot.db') as target:
        source.backup(target)
with sqlite3.connect(backup / 'bot.db') as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
# Test restoring to a separate file, without touching the live database.
with sqlite3.connect(backup / 'bot.db') as source:
    with sqlite3.connect(backup / 'restore-test.db') as target:
        source.backup(target)
with sqlite3.connect(backup / 'restore-test.db') as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print('SQLite backup and restore check: OK')
PY
printf 'Backup location: %s\n' "$backup_dir"
```

مسیر backup را برای rollback نگه دارید. دسترسی backup باید فقط برای مدیر باشد؛
شامل داده کاربران و کلیدها است. اگر backup یا تست بازیابی شکست خورد، نصب را
ادامه ندهید و سرویس قبلی را دوباره روشن کنید.

## نصب و راه‌اندازی

با ویرایشگر امن، `ABSTRACT_API_KEY` را به `.env` فعلی اضافه کنید؛ مقادیر قبلی
را حفظ کنید و کلید را در فرمان shell، تاریخچه یا Git ننویسید. دسترسی `.env`
فقط برای مالک/کاربر سرویس مجاز باشد. HTTPS خروجی به
`emailreputation.abstractapi.com`، `leakcheck.io` و `api.telegram.org` لازم است.

از همان پوشه staging و در همان نشست root:

```bash
cp -a /opt/radepa-stage-abstract/Radepa-Channel-Update/Radepa-server-review/app/. /opt/radepa/app/
/opt/radepa/venv/bin/python -m pip install -r /opt/radepa-stage-abstract/Radepa-Channel-Update/Radepa-server-review/requirements.txt
/opt/radepa/venv/bin/python -m pip check
cd /opt/radepa
/opt/radepa/venv/bin/python - <<'PY'
from dotenv import load_dotenv
load_dotenv('/opt/radepa/.env', override=True)
import app.main
print('Application import: OK')
PY
```

وابستگی جدیدی برای AbstractAPI اضافه نشده است؛ venv قبلی حفظ می‌شود. مالکیت
فایل‌های کپی‌شده را با کاربر واقعی سرویس تطبیق دهید. کد با دیتابیس و `.env`
نمونه جایگزین نمی‌شود. تست زنده زیر فقط یک آدرس ساختگی example.com را می‌فرستد،
ممکن است سهمیه AbstractAPI مصرف کند و اعتبار ربات را تغییر نمی‌دهد:

```bash
cd /opt/radepa-stage-abstract/Radepa-Channel-Update/Radepa-server-review
/opt/radepa/venv/bin/python - <<'PY'
import runpy
from dotenv import load_dotenv
load_dotenv('/opt/radepa/.env', override=True)
runpy.run_path('tools/check_abstract_connection.py', run_name='__main__')
PY
systemctl start radepa.service
systemctl is-active --quiet radepa.service
```

فعال بودن سرویس کافی نیست. با حساب آزمایشی خود `/start` و سپس `/email` را
بررسی کنید: دو منبع، بخش‌های ریسک/کیفیت/تحویل، فایل TXT، حذف منابع تکراری و
کاهش دقیقاً یک اعتبار. برای خطای یک سرویس نتیجه دیگری باید حفظ شود؛ تست‌های
آفلاین قطع هر دو و بازپرداخت را پوشش می‌دهند. لاگ‌ها را فقط محلی و با حذف
اطلاعات حساس بررسی کنید. خطای ساختار پاسخ واقعی باید قبل از عرضه رفع شود.

## بازگشت

در صورت شکست، سرویس را متوقف و کد و venv قبلی را بازگردانید. مسیر backup واقعی
را در نشست تنظیم کنید. برای حذف فایل‌های جدیدِ app، کل پوشه را جایگزین کنید؛
صرفاً کپی روی آن کافی نیست. ابتدا وضعیت شکست‌خورده را هم حفظ کنید.

```bash
systemctl stop radepa.service
mv /opt/radepa/app "$backup_dir/failed-app"
cp -a "$backup_dir/app" /opt/radepa/app
mv /opt/radepa/venv "$backup_dir/failed-venv"
cp -a "$backup_dir/venv" /opt/radepa/venv
cp -p "$backup_dir/.env" /opt/radepa/.env
cp -p "$backup_dir/requirements.txt" /opt/radepa/requirements.txt
```

بازیابی دیتابیس را فقط اگر مهاجرت ناسازگار شده و با پذیرش از دست رفتن تمام
تراکنش‌های پس از backup لازم است انجام دهید؛ rollback کد به‌تنهایی نباید
سفارش‌ها و اعتبارهای جدید را پاک کند. پیش از بازیابی دیتابیس، از وضعیت فعلی
هم با SQLite backup نسخه بگیرید. سپس با سرویس خاموش و اتصال SQLite بسته، فایل
`bot.db` معتبر backup را جایگزین کنید، فایل‌های قدیمی `bot.db-wal` و `bot.db-shm`
را پس از اطمینان از نبود هیچ پردازش متصل کنار بگذارید و مالکیت را اصلاح کنید.
در پایان `systemctl start radepa.service` و تست `/start` را انجام دهید.
