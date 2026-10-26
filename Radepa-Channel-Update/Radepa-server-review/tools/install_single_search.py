from pathlib import Path
import hashlib, json, os, shutil, sqlite3, subprocess, tempfile, time

live = Path('/opt/radepa')
stage = Path('/tmp/radepa-update/radepa-codex-single-search-payments-20261026/Radepa-Channel-Update/Radepa-server-review')
python = live / 'venv/bin/python'
unit = 'radepa.service'
assert os.geteuid() == 0, 'Run this installer as root'

def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Command failed; output withheld to protect settings')
    return result.stdout.decode().strip()

def fingerprint(folder):
    digest = hashlib.sha256()
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.sql'):
            if path.is_symlink():
                raise RuntimeError('Unexpected source symlink')
            data = path.read_bytes().replace(b'\r\n', b'\n')
            digest.update((path.relative_to(folder).as_posix() + ' ' + hashlib.sha256(data).hexdigest() + '\n').encode())
    return digest.hexdigest()

def copy_db(source, destination):
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Database integrity check failed')

def clear_cache():
    for path in (live / 'app').rglob('__pycache__'):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)

assert fingerprint(live / 'app') == '28415ba362e72cc678f313b8d81c1402446c354de59cb3c8499c46f74d213b7d', 'Live source changed; aborting'
assert fingerprint(stage / 'app') == 'dfefdd880ec9e1fa86caa3052ec54e015ee5b126d737e5731394989bfd09526b', 'Staged source incomplete or changed; aborting'
pid = int(run(['systemctl', 'show', unit, '-p', 'MainPID', '--value']))
assert pid > 0, 'Expected running service'
# Reuse service environment internally. Never print credentials or environment values.
runtime = dict(item.split('=', 1) for item in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in item)
runtime['PYTHONDONTWRITEBYTECODE'] = '1'
relative_db = run([python, '-c', 'from app.config import config; print(config.db_path)'], cwd=live, env=runtime)
db = Path(relative_db)
if not db.is_absolute():
    db = live / db
db = db.resolve()
assert db.is_file(), 'Configured database is missing'
backup_root = Path('/root/radepa-backups')
backup_root.mkdir(mode=0o700, exist_ok=True)
backup = Path(tempfile.mkdtemp(prefix='single-search-', dir=backup_root))
print('BACKUP:', backup, flush=True)
shutil.copytree(live / 'app', backup / 'app', symlinks=True)
if (live / '.env').is_file():
    shutil.copy2(live / '.env', backup / '.env')
(backup / 'database-path.txt').write_text(str(db))
changed = [p.relative_to(stage) for p in sorted((stage / 'app').rglob('*')) if p.is_file() and p.suffix in ('.py', '.sql') and (not (live / p.relative_to(stage)).exists() or p.read_bytes() != (live / p.relative_to(stage)).read_bytes())]
(backup / 'changed-files.json').write_text(json.dumps([str(p) for p in changed]))
installed = False
try:
    print('PHASE: stop service and back up database', flush=True)
    run(['systemctl', 'stop', unit])
    assert run(['systemctl', 'show', unit, '-p', 'MainPID', '--value']) == '0', 'Service did not stop'
    copy_db(db, backup / 'bot.db')
    copy_db(backup / 'bot.db', backup / 'migration-test.db')
    test_env = {**runtime, 'DB_PATH': str(backup / 'migration-test.db'), 'LOG_FILE': str(backup / 'test.log')}
    print('PHASE: test migration on backup copy', flush=True)
    run([python, '-c', "from dotenv import load_dotenv; load_dotenv('/opt/radepa/.env'); import app.main; from app.db.database import init_db; from app.services.products import seed_products; from app.config import config; init_db(config.db_path); seed_products()"], cwd=stage, env=test_env)
    with sqlite3.connect(backup / 'migration-test.db') as connection:
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    print('PHASE: install application files', flush=True)
    installed = True
    for relative in changed:
        destination = live / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage / relative, destination)
    clear_cache()
    run(['systemctl', 'start', unit])
    time.sleep(5)
    run(['systemctl', 'is-active', '--quiet', unit])
    print('INSTALL_OK: service process is active. Verify /start, /plans, /help and a test search in Telegram.')
except BaseException:
    print('INSTALL_FAILED: restoring previous version. Backup:', backup, flush=True)
    if installed:
        run(['systemctl', 'stop', unit])
        assert run(['systemctl', 'show', unit, '-p', 'MainPID', '--value']) == '0'
        for relative in changed:
            original = backup / relative
            destination = live / relative
            if original.exists():
                shutil.copy2(original, destination)
            elif destination.exists():
                destination.unlink()
        clear_cache()
        copy_db(backup / 'bot.db', db)
    run(['systemctl', 'start', unit])
    time.sleep(3)
    run(['systemctl', 'is-active', '--quiet', unit])
    print('ROLLBACK_SERVICE_ACTIVE: previous version restored. Keep the backup.')
    raise SystemExit(1)
