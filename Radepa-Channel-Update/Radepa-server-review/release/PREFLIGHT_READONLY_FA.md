# Preflight فقط‌خواندنی سرور Radepa

این چک‌لیست برای جمع‌آوری شواهد است، نه نصب. هیچ دستور deploy، restart، stop، migration، pip install یا تغییر تنظیمات ندارد. در این بررسی روی سرور اصلی اجرا نشده است. پیش از پذیرش انتشار، خروجی تازه لازم است؛ خروجی قدیمی گفتگو، اثبات وضعیت فعلی نیست.

## شواهد لازم

- [ ] Ubuntu با ID برابر ubuntu و VERSION_ID برابر 22.04.
- [ ] Python سیستم و Python محیط فعال حداقل 3.10 و نسخه نهایی باشند؛ 3.11.0rc1 پذیرش نمی‌شود.
- [ ] سرویس loaded، active و running و MainPID مثبت باشد؛ وضعیت unhealthy را با restart اصلاح نکنید، فقط گزارش کنید.
- [ ] کاربر سرویس root یا مقدار خالی پیش‌فرض systemd، WorkingDirectory=/opt/radepa و ExecStart مطابق الگوی نصب‌کننده باشد.
- [ ] app، venv، requirements.txt و .env در /opt/radepa موجود باشند؛ محتوای .env منتشر نشود.
- [ ] fingerprint کد روی دیسک با یکی از سه baseline زیر برابر باشد؛ Git SHA یا نام پوشه به‌تنهایی کافی نیست.
- [ ] نتیجه فقط شواهد ساختار و کد روی دیسک است. کلیدهای سرویس، DB_PATH مؤثر، اجرای کد روی دیتابیس واقعی و انطباق کد بارگذاری‌شده در حافظه با دیسک بررسی نمی‌شوند؛ این preflight تضمین کامل نصب نیست.

| نسخه مبنا | fingerprint کامل app (الگوریتم نصب‌کننده) |
|---|---|
| توسعه پشتیبانی/ادمین، 3ea86bb | `8c47d5b1f33c054634f0cb38c277e6eb6d0d905d8485fdef9bb8c97bf45d6aae` |
| نسخه رسید قبل از توسعه پشتیبانی | `48758402df33524ddb829959fd4a0a539bcb9ca55717ffeeeef6ad1a22c639e7` |
| AbstractAPI، 17ca5cb | `4fd9a784fad76896dbc783678610720856364b1ce8e1d9e467bdf8898d5a3874` |

## دستور جمع‌آوری روی نشست مجاز PuTTY

این بلوک را می‌توان در نشست فعلی مدیر سرور اجرا کرد. خروجی فقط نسخه، وضعیت، مسیرهای غیرمحرمانه و هش است؛ هیچ import از app، خواندن .env، بازکردن SQLite یا چاپ Environment/ExecStart خام انجام نمی‌دهد. -B مانع ساخت pyc است. بررسی فایل‌ها ممکن است طبق تنظیم filesystem زمان دسترسی atime را تغییر دهد؛ «فقط‌خواندنی» در اینجا یعنی نبود تغییر عمدی در کد، تنظیمات، دیتابیس و سرویس.

```bash
python3 -B - <<'PY'
import hashlib, json, os, subprocess, sys
from pathlib import Path

live = Path('/opt/radepa')
known = {
    '8c47d5b1f33c054634f0cb38c277e6eb6d0d905d8485fdef9bb8c97bf45d6aae': 'admin-support',
    '48758402df33524ddb829959fd4a0a539bcb9ca55717ffeeeef6ad1a22c639e7': 'receipt-review',
    '4fd9a784fad76896dbc783678610720856364b1ce8e1d9e467bdf8898d5a3874': 'abstract-email',
}
report = {}
def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('Read-only command failed')
    return result.stdout.strip()
def fingerprint():
    app = live / 'app'
    if not app.is_dir() or app.is_symlink():
        raise ValueError('Missing or symlinked app')
    digest = hashlib.sha256()
    count = 0
    for path in sorted(app.rglob('*')):
        if path.is_symlink():
            raise ValueError('Source symlink')
        if path.is_file() and path.suffix in ('.py', '.sql'):
            count += 1
            data = path.read_bytes().replace(b'\r\n', b'\n')
            digest.update((path.relative_to(app).as_posix() + ' ' + hashlib.sha256(data).hexdigest() + '\n').encode())
    if not count:
        raise ValueError('Empty app')
    return digest.hexdigest()
try:
    os_info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    report['os'] = {key: os_info.get(key, '').strip('"') for key in ('ID', 'VERSION_ID')}
    report['system_python'] = sys.version.split()[0]
    report['system_python_supported'] = sys.version_info >= (3, 10) and sys.version_info.releaselevel == 'final'
    fields = ('LoadState', 'ActiveState', 'SubState', 'MainPID', 'User', 'WorkingDirectory', 'ExecStart')
    args = ['systemctl', 'show', 'radepa.service']
    for field in fields:
        args += ['-p', field]
    unit = dict(line.split('=', 1) for line in command(args).splitlines() if '=' in line)
    report['service'] = {key: unit.get(key, '') for key in fields if key != 'ExecStart'}
    report['execstart_matches_installer'] = str(live / 'venv/bin/python') in unit.get('ExecStart', '') and 'app.main' in unit.get('ExecStart', '')
    report['files_present'] = {name: (live / name).exists() for name in ('app', 'venv/bin/python', 'requirements.txt', '.env')}
    settings = live / '.env'
    report['env_private'] = settings.is_file() and not settings.is_symlink() and (settings.stat().st_mode & 0o077) == 0
    version_code = 'import json,sys;print(json.dumps({"version":sys.version.split()[0],"supported":sys.version_info>=(3,10) and sys.version_info.releaselevel=="final"}))'
    report['service_python'] = json.loads(command([str(live / 'venv/bin/python'), '-I', '-B', '-c', version_code]))
    first = fingerprint()
    report['app_fingerprint'] = first
    report['baseline'] = known.get(first, 'UNKNOWN')
    report['source_stable_during_check'] = fingerprint() == first
    checks = [report['os'] == {'ID': 'ubuntu', 'VERSION_ID': '22.04'}, report['system_python_supported'],
              report['service_python']['supported'], unit.get('LoadState') == 'loaded',
              unit.get('ActiveState') == 'active', unit.get('SubState') == 'running',
              int(unit.get('MainPID', '0')) > 0, unit.get('User') in ('', 'root'),
              unit.get('WorkingDirectory') == str(live), report['execstart_matches_installer'],
              all(report['files_present'].values()), report['env_private'], first in known,
              report['source_stable_during_check']]
    report['result'] = 'READONLY_CHECKS_PASS' if all(checks) else 'BLOCKED'
except Exception as exc:
    report['result'] = 'BLOCKED'
    report['error_type'] = type(exc).__name__
print(json.dumps(report, indent=2))
sys.exit(0 if report['result'] == 'READONLY_CHECKS_PASS' else 1)
PY
```

برای اشتراک خروجی، فقط همین JSON کافی است؛ .env، journal خام، systemctl cat یا فهرست متغیرهای محیطی را نفرستید. UNKNOWN، خطای دسترسی، Python پیش‌انتشار، drift یا سرویس غیرفعال یعنی پذیرش متوقف است؛ هیچ baseline جدیدی صرفاً برای عبور از بررسی به allowlist اضافه نکنید.

## وضعیت فعلی تطابق

در ۲۰۲۶-۱۱-۰۱، محیط بررسی فاقد اعتبارنامه SSH و مسیر TCP مجاز سرور است. /opt/radepa این محیط نیز نصب فعال ربات نیست. بنابراین fingerprint فعلی سرور و نسخه Python مؤثر **نامعلوم و مسدودکننده پذیرش** هستند. گزارش قدیمی ALREADY_CURRENT فقط قرینه تاریخی است و جای خروجی تازه بالا را نمی‌گیرد.
