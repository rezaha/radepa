"""Deploy receipt review to the known /opt/radepa installation, with code rollback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time

EXPECTED = '48758402df33524ddb829959fd4a0a539bcb9ca55717ffeeeef6ad1a22c639e7'
BASELINES = {
    '4fd9a784fad76896dbc783678610720856364b1ce8e1d9e467bdf8898d5a3874',
    '029f5e1faa68781c203cb53406b787f6c0c647f869605d7082ff406d9251b044',
}
UNIT = 'radepa.service'


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Command failed; sensitive output withheld')
    return result.stdout.strip()


def fingerprint(folder):
    digest = hashlib.sha256()
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.sql'):
            if path.is_symlink() or path.resolve() != path.absolute():
                raise RuntimeError('Source symlinks are not supported')
            data = path.read_bytes().replace(b'\r\n', b'\n')
            digest.update((path.relative_to(folder).as_posix() + ' ' + hashlib.sha256(data).hexdigest() + '\n').encode())
    return digest.hexdigest()


def runtime_environment(pid):
    env = dict(item.split('=', 1) for item in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in item)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def copy_db(source, destination):
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Database integrity check failed')


def clear_cache(live):
    for path in (live / 'app').rglob('__pycache__'):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)


def deploy(stage, live=Path('/opt/radepa'), backup_root=Path('/root/radepa-backups')):
    if os.geteuid() != 0:
        raise RuntimeError('Run as root')
    if fingerprint(stage / 'app') != EXPECTED:
        raise RuntimeError('Staged source incomplete or changed')
    current = fingerprint(live / 'app')
    if current == EXPECTED:
        run(['systemctl', 'is-active', '--quiet', UNIT])
        print('ALREADY_CURRENT: source matches; service process is active.')
        return
    if current not in BASELINES:
        raise RuntimeError('Live source is unknown or modified; no changes made')
    if (live / 'requirements.txt').read_bytes().replace(b'\r\n', b'\n') != (stage / 'requirements.txt').read_bytes().replace(b'\r\n', b'\n'):
        raise RuntimeError('Dependency requirements differ; no changes made')
    if run(['systemctl', 'show', UNIT, '-p', 'User', '--value']) not in ('root', ''):
        raise RuntimeError('Service user differs from the verified root installation')
    if run(['systemctl', 'show', UNIT, '-p', 'WorkingDirectory', '--value']) != str(live):
        raise RuntimeError('Unexpected service working directory')
    pid = int(run(['systemctl', 'show', UNIT, '-p', 'MainPID', '--value']))
    if pid <= 0:
        raise RuntimeError('Expected running service')
    python = live / 'venv/bin/python'
    env = runtime_environment(pid)
    db = Path(run([python, '-B', '-c', 'from app.config import config; print(config.db_path)'], cwd=live, env=env))
    if not db.is_absolute():
        db = live / db
    db = db.resolve()
    if not db.is_file():
        raise RuntimeError('Configured database is missing')
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='receipt-review-', dir=backup_root))
    shutil.copytree(live / 'app', backup / 'app', symlinks=True)
    for name in ('.env', 'requirements.txt'):
        if (live / name).is_file():
            shutil.copy2(live / name, backup / name)
    (backup / 'database-path.txt').write_text(str(db))
    print('BACKUP:', backup, flush=True)
    installed = False
    try:
        run(['systemctl', 'stop', UNIT])
        if run(['systemctl', 'show', UNIT, '-p', 'MainPID', '--value']) != '0':
            raise RuntimeError('Service did not stop')
        copy_db(db, backup / 'bot.db')
        copy_db(backup / 'bot.db', backup / 'restore-test.db')
        print('Database backup and restore check: OK', flush=True)
        test_env = {**env, 'DB_PATH': str(backup / 'restore-test.db'), 'LOG_FILE': str(backup / 'test.log')}
        check = (f'from dotenv import load_dotenv; load_dotenv({str(live / ".env")!r}); '
                 'import app.main; from app.config import config; '
                 'from app.db.database import init_db; init_db(config.db_path)')
        run([python, '-B', '-c', check], cwd=stage, env=test_env)
        installed = True
        shutil.copytree(stage / 'app', live / 'app', dirs_exist_ok=True)
        clear_cache(live)
        run(['systemctl', 'start', UNIT])
        time.sleep(5)
        run(['systemctl', 'is-active', '--quiet', UNIT])
        print('INSTALL_OK: service process is active. Verify a receipt in Telegram /admin.')
    except BaseException:
        print('INSTALL_FAILED: restoring previous application. Backup:', backup, flush=True)
        if installed:
            run(['systemctl', 'stop', UNIT])
            if run(['systemctl', 'show', UNIT, '-p', 'MainPID', '--value']) != '0':
                raise RuntimeError('Cannot stop service for rollback; manual recovery required')
            shutil.move(str(live / 'app'), str(backup / 'failed-app'))
            shutil.copytree(backup / 'app', live / 'app', symlinks=True)
            clear_cache(live)
        # These supported releases share the same schema. Never erase newer payments.
        run(['systemctl', 'start', UNIT])
        time.sleep(3)
        run(['systemctl', 'is-active', '--quiet', UNIT])
        print('ROLLBACK_SERVICE_ACTIVE: previous code restored; live database retained.')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    deploy(parser.parse_args().stage.resolve())
