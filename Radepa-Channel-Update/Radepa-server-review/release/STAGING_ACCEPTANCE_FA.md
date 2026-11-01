# پذیرش نهایی staging برای بسته d2dfd8b

**وضعیت جدید:** مراحل این سند بعداً در CI و سرور موفق شدند و مدیر نصب واقعی را جداگانه تأیید کرد. [ثبت نصب و پذیرش اولیه](DEPLOYMENT_ACCEPTANCE_FA.md) وضعیت جدید را دارد؛ بخش «توقف فعلی» پایین سابقه مانع قبل از رفع وابستگی‌هاست. دستورات نصب را دوباره اجرا نکنید.

این راهنما فقط روی یک VM مستقل Ubuntu 22.04 اجرا شود؛ نه روی 195.248.243.50. هیچ دستور deploy، restart یا merge در این فرایند وجود ندارد. نصب پکیج و ایجاد فایل در این سند مختص VM آزمایشی است. Preflight سرور اصلی در [PREFLIGHT_READONLY_FA.md](PREFLIGHT_READONLY_FA.md) جدا و فقط‌خواندنی است.

## وضعیت مشاهده‌شده PR

در ۲۰۲۶-۱۱-۰۱، صفحه رسمی [PR #1](https://github.com/rezaha/radepa/pull/1) وضعیت DRAFT، mergedTime=null و closedTime=null داشت. head برابر `d2dfd8bb82abd3d0e72f50e36ebabbc52029ae1f` و main برابر `74cbda2884a5b50e6c9c5caea716d01fc9230b44` بود؛ git ls-remote نیز این دو SHA را تأیید کرد. عنوان: Add admin-only Instagram recovery page inspector (read-only).

دسترسی GraphQL با gh در این محیط Forbidden بود؛ وضعیت از JSON موجود در صفحه رسمی GitHub خوانده شد، نه از cache محلی Git. وضعیت CI و mergeability از این مشاهده نتیجه‌گیری نمی‌شود. commit مستندات پذیرش، پس از این مشاهده به همان شاخه اضافه می‌شود؛ بسته pin‌شده d2dfd8b تغییر نمی‌کند.

## VM جدا و دریافت بسته

از VM تازه Ubuntu 22.04 با Python نهایی حداقل 3.10 استفاده کنید. python3-venv و ca-certificates باید نصب باشند؛ در صورت نیاز فقط روی همین VM:

```bash
sudo apt-get install -y python3-venv ca-certificates
```

از root غیرضروری پرهیز کنید؛ حساب staging مستقل کافی است. فایل .env، دیتابیس، توکن یا venv Production را به VM منتقل نکنید. در یک نشست Bash، این بلوک را اجرا کنید؛ اگر پوشه از قبل وجود داشته باشد، mkdir باعث توقف می‌شود تا داده قبلی بازنویسی نشود:

```bash
set -euo pipefail
umask 077
radepa_acceptance_dir="$HOME/radepa-acceptance-d2dfd8b"
mkdir "$radepa_acceptance_dir"
cd "$radepa_acceptance_dir"
curl --fail --location --show-error \
  'https://raw.githubusercontent.com/rezaha/radepa/d2dfd8bb82abd3d0e72f50e36ebabbc52029ae1f/Radepa-Channel-Update/Radepa-server-review/release/dist/radepa-instagram-release.zip' \
  --output radepa-instagram-release.zip
printf '%s\n' '5ff8e812d5c4a2adfdb76d016a41d90dc4b4752252cdd77ccac4f8208e83ec1f  radepa-instagram-release.zip' | sha256sum --check -
python3 -m zipfile -t radepa-instagram-release.zip
python3 -m zipfile -e radepa-instagram-release.zip extracted
cd extracted/radepa-release
python3 - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path('release-manifest.json').read_text())
assert manifest['source_commit'] == '38fd00aebaef3e951fb7a551009e05e693b8bec5'
print('Pinned source commit: OK')
PY
python3 -m venv "$radepa_acceptance_dir/browser-setup"
"$radepa_acceptance_dir/browser-setup/bin/python" -m pip install playwright==1.64.1
sudo "$radepa_acceptance_dir/browser-setup/bin/python" -m playwright install-deps chromium
"$radepa_acceptance_dir/browser-setup/bin/python" -m playwright install --dry-run chromium
python3 -B tools/release_manager.py stage --source "$PWD" --root "$HOME/radepa-stages"
```

ابزار stage مرورگر رسمی، venv و state مستقل می‌سازد. سرویس systemd و توکن واقعی استفاده نمی‌شود؛ run_polling mock است. آزمون مرورگر فقط به HTTP fixture روی loopback وصل می‌شود. متن «Bot starting — polling mode» در لاگ smoke به معنی polling واقعی نیست. حالت --without-browser فقط برای عیب‌یابی است و پذیرش نهایی محسوب نمی‌شود.

## مسیر مجاز نصب Chromium

نصب‌کننده Playwright نسخه pin‌شده، مرجع URL و revision مرورگر است. خروجی install --dry-run بالا، بدون دانلود، مقصدهای دقیق را نشان می‌دهد. در این بررسی روی Linux x86_64:

| مؤلفه | مقصد اعلام‌شده Playwright 1.64.1 |
|---|---|
| Chromium و Headless Shell، revision 1248 | `https://cdn.playwright.dev/builds/cft/156.0.8078.4/linux64/` |
| FFmpeg، revision 1013 | `https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-linux.zip` |
| fallback رسمی FFmpeg | `https://playwright.download.prss.microsoft.com/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-linux.zip` و `https://cdn.playwright.dev/builds/ffmpeg/1013/ffmpeg-linux.zip` |

برای معماری دیگر، خروجی واقعی dry-run ملاک است. PyPI و files.pythonhosted.org برای وابستگی‌های Python، و مخازن رسمی Ubuntu برای کتابخانه‌های سیستم لازم‌اند. TLS فعال بماند و proxy و CA سازمانی مجاز حفظ شوند.

مسیر اول، درخواست دسترسی از مدیر شبکه به مقصد رسمی و redirectهای واقعی همان دانلود است. در محیط cloud، این تغییر از workflow پشتیبانی‌شده تنظیمات شبکه انجام می‌شود؛ ویرایش network-policy.json یا تغییر مسیر اتصال، مجوز ایجاد نمی‌کند. در این کار policy تغییر نکرده است.

مسیر دوم، استفاده از مخزن داخلی سازمانی تأییدشده است که همان فایل‌های upstream را با کنترل منشأ و SHA256 منتشر می‌کند. Playwright رسماً PLAYWRIGHT_DOWNLOAD_HOST و PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST را پشتیبانی می‌کند؛ فقط اگر چنین مخزنی از قبل توسط مدیر شبکه تأیید شده، آدرس HTTPS معتبرش را برای نشست staging تنظیم کنید. برای FFmpeg نیز مسیر پیش‌فرض یا mirror کامل باید مجاز باشد. مقدار آزمایشی یا mirror عمومی ناشناس وارد نکنید. تغییر این متغیرها نباید ابزاری برای فرار از منع مقصد باشد.

مرجع رسمی تنظیم proxy، CA و download host: [Playwright Python — Browsers](https://playwright.dev/python/docs/browsers). وجود دو متغیر download host در driver نصب‌شده نسخه 1.64.1 نیز بررسی شد؛ URLهای جدول از خروجی واقعی dry-run همان نسخه‌اند.

مسیر سوم، VM آزمایشی دیگری با دسترسی سازمانی مجاز به همان CDN است. نتیجه آن، دسترسی این محیط یا Production را اثبات نمی‌کند؛ شواهد همان VM، معماری و نسخه بسته را ثبت کنید. انتقال کورکورانه cache مرورگر بین معماری‌ها یا نصب Chrome سیستم به جای bundled Chromium، پذیرش این بسته نیست.

در خطای certificate، زنجیره CA تأییدشده را در trust store VM و در صورت نیاز NODE_EXTRA_CA_CERTS به Node معرفی کنید؛ TLS همچنان اعتبارسنجی شود. از curl -k، NODE_TLS_REJECT_UNAUTHORIZED=0، HTTP بدون TLS، حذف پراکسی، host-network یا تغییر DNS برای دورزدن منع استفاده نکنید. timeout بیشتر، HTTP 403 سیاست شبکه را رفع نمی‌کند.

## تأیید ready.json و آزمون مرورگر

فقط وقتی stage با exit code صفر و STAGE_READY تمام شد، مسیر چاپ‌شده آن را انتخاب کنید. ready.json را دستی نسازید یا browser را ویرایش نکنید. مرحله شکست‌خورده را با اجرای تازه stage جایگزین کنید، نه دستکاری نشانگرها.

در VM آزمایشی، مسیر واقعی را به جای نمونه زیر بگذارید. این بررسی فقط فایل‌های مرحله و pip freeze را می‌خواند؛ تابع deploy را صدا نمی‌زند:

```bash
radepa_checked_stage="$HOME/radepa-stages/radepa-REPLACE_WITH_REAL_ID"
python3 -B - "$radepa_checked_stage" <<'PY'
import hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

stage = Path(sys.argv[1]).resolve()
source = stage / 'source'
spec = importlib.util.spec_from_file_location('release_manager', source / 'tools/release_manager.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
verified_source, ready = manager.check_stage(stage)
manifest = json.loads((source / 'release-manifest.json').read_text())
health = json.loads((stage / 'state/health.json').read_text())
assert manifest['source_commit'] == '38fd00aebaef3e951fb7a551009e05e693b8bec5'
assert ready['browser'] is True
assert health['startup_without_playwright'] == 'passed'
assert health['chromium_local_fixture'] == 'passed'
tests = health['tests']
assert tests['run'] == 135 and tests['failures'] == 0 and tests['errors'] == 0
assert type(tests['skipped']) is int and tests['skipped'] in (0, 1)
env = manager.isolated_env(stage)
probe = '''import json,os,sys
from pathlib import Path
from importlib.metadata import version
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    executable = Path(p.chromium.executable_path).resolve()
    browsers = Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).resolve()
    info = {'python':sys.version.split()[0], 'stable':sys.version_info.releaselevel=='final',
            'supported':sys.version_info>=(3,10), 'ptb':version('python-telegram-bot'),
            'playwright':version('playwright'), 'browser_exists':executable.is_file(),
            'browser_executable':os.access(executable, os.X_OK),
            'inside_stage_cache':executable.is_relative_to(browsers)}
    print(json.dumps(info))
'''
result = subprocess.run([str(stage / 'venv/bin/python'), '-I', '-B', '-c', probe],
                        env=env, capture_output=True, text=True, check=True, timeout=30)
info = json.loads(result.stdout)
assert info['stable'] and info['supported'] and info['ptb'] == '21.5' and info['playwright'] == '1.64.1'
assert info['browser_exists'] and info['browser_executable'] and info['inside_stage_cache']
os_info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
assert os_info.get('ID', '').strip('"') == 'ubuntu' and os_info.get('VERSION_ID', '').strip('"') == '22.04'
print(json.dumps({'result':'STAGING_EVIDENCE_PASS', 'source_commit':manifest['source_commit'],
                  'manifest_sha256':hashlib.sha256((source / 'release-manifest.json').read_bytes()).hexdigest(),
                  'health':health, 'runtime':info}, indent=2))
PY
```

check_stage تمامیت manifest و فایل‌ها، fingerprint برنامه و pip freeze را با ready مقایسه می‌کند. این کافی نیست که فقط JSON ظاهراً browser=true داشته باشد؛ health مستقل هم باید chromium_local_fixture=passed و startup_without_playwright=passed داشته باشد. تنها skip تعریف‌شده در سورس pin‌شده، LocalBrowserTests.test_real_browser_on_local_fixture در tests/test_instagram_inspector_runtime.py است: شرط shutil.which('chromium') و علت System Chromium not available. در VM فاقد Chromium سیستم، یک skip از این تست مجاز است؛ هر skip دیگر توقف ایجاد می‌کند. smoke.log با verbosity=1 نام یا علت skip را چاپ نمی‌کند؛ شمارش آن را همراه شرط همین تست در سورس تأییدشده بررسی کنید. smoke مستقل bundled Chromium هرگز نباید skip شده باشد.

این آزمون شواهد آزمون موفق قبلی و وجود executable را بررسی می‌کند؛ مرورگر را دوباره اجرا نمی‌کند. برای اثبات اجرای تازه پس از تغییر VM یا کتابخانه‌ها، stage تازه بسازید. ready/health امضای رمزنگاری‌شده نیستند و نباید از منبع ناشناس یا stage دستکاری‌شده پذیرفته شوند. موفقیت محلی اثبات دسترسی زنده Instagram، رفتار API پولی یا آزمون تعاملی Telegram نیست.

## خروجی پذیرش و توقف فعلی

- [ ] SHA256 ZIP و source_commit pin‌شده صحیح‌اند.
- [ ] Ubuntu 22.04، Python نهایی و نسخه‌های دقیق PTB/Playwright تأیید شده‌اند.
- [ ] stage پیش‌فرض بدون --without-browser موفق است؛ مرورگر از cache مستقل همین stage می‌آید.
- [ ] خروجی STAGING_EVIDENCE_PASS و بررسی علت هر skip ثبت شده است.
- [ ] JSON تازه Preflight اصلی، baseline شناخته‌شده و سرویس مطابق ساختار پشتیبانی‌شده دارد.
- [ ] هیچ دستور deploy/restart/merge اجرا نشده؛ موفقیت این چک‌لیست مجوز نصب Production نیست.

در بررسی فعلی **پذیرش نهایی مسدود است**: CDN رسمی در policy فعلی مجاز نیست و اجرای bundled Chromium روی Ubuntu تأیید نشده است. طبق Preflight واقعی گزارش‌شده توسط مدیر پروژه، baseline سرور admin-support و مطابق است، اما Python محیط فعال 3.11.0rc1 است. [برنامه Python 3.10 مستقل](PYTHON310_STAGING_FA.md) مسیر بررسی محیط پایدار جدید را مشخص می‌کند؛ venv فعلی تغییر نمی‌کند. شاهد آماده browser=true وجود ندارد و نشانگر جایگزین ساخته نشده است. گزارش قبلی تست‌های موفق Python و مرورگر سیستم در VALIDATION_FA.md معتبر است، اما این موانع را رفع نمی‌کند. نصب متوقف بماند.

## اعتبارسنجی همین راهنما

بلوک‌های Bash با bash -n و بلوک‌های Python با compile بررسی شدند. ۱۵ سناریو با فایل‌های موقت و mock کامل probeهای سیستم/مرورگر اجرا شدند: پذیرش شواهد سالم، رد browser=false، health ناموفق، تست‌های ناقص یا شکست‌خورده، skip اضافی، مرورگر خارج از cache یا حذف‌شده، PTB اشتباه، Python پیش‌انتشار، دستکاری سورس، سرویس غیرفعال و baseline ناشناخته. آزمون Preflight همچنین تأیید کرد متن محرمانه آزمایشی ExecStart در خروجی چاپ نمی‌شود. این آزمون‌های شبیه‌سازی جایگزین اجرای واقعی Ubuntu/Chromium یا Preflight سرور نیستند. کد اجرایی ربات، بسته ZIP و checksum قبلی در این مرحله تغییر نکرده‌اند.
