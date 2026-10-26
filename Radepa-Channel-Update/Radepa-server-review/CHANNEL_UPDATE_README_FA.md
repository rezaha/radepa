# افزونه کانال ردپا

کانال: https://t.me/Radepa_Updates

- دکمه کانال به Reply Keyboard و Inline Menu اضافه می‌شود.
- `/channel` لینک مستقیم کانال را می‌فرستد.
- `/channelstats` فقط برای ادمین، تعداد اعضای کانال را از تلگرام می‌گیرد. برای موفقیت در دریافت آمار، ربات را به کانال اضافه کرده و دسترسی مناسب بدهید.
- دیتابیس و `.env` تغییری نمی‌کنند؛ شمارنده Monthly Users پروفایل ربات توسط تلگرام کنترل می‌شود.
- هیچ عضویت اجباری فعال نیست.

## نصب
در PowerShell ویندوز (فایل ZIP را در Downloads قرار دهید):

```powershell
scp "$HOME\Downloads\Radepa-Channel-Update.zip" root@195.248.243.50:/tmp/
ssh root@195.248.243.50
```

در SSH لینوکس سرور:

```bash
mkdir -p /tmp/radepa-channel-install
unzip -q /tmp/Radepa-Channel-Update.zip -d /tmp/radepa-channel-install
bash /tmp/radepa-channel-install/Radepa-server-review/install-channel-update.sh
```

نصاب ابتدا هش نسخه فایل‌های موجود سرور را بررسی می‌کند و اگر تفاوت داشته باشند بدون تغییر متوقف می‌شود. پیش از جایگزینی از کد، `.env` و دیتابیس پشتیبان می‌گیرد و اگر راه‌اندازی شکست بخورد کد را برمی‌گرداند.

پس از نصب در تلگرام `/start` و `/channel` را امتحان کنید. برای `/channelstats` ربات باید بتواند شمار اعضای کانال را بخواند.
