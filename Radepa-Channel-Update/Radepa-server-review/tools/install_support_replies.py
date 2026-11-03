"""Guarded app-only support update. Default is read-only; installation needs --apply."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_manager as runtime

LIVE = Path('/opt/radepa')
UNIT = 'radepa.service'
EXPECTED = '1ede48f63866949e8e65c96082f1797b6fb38e84f266c8a68aa26f7fe50b7e85'
BASELINES = {'de56f1a58dba35493a6acc459fc584997dfbdbfc7723f0ae44bde157c8a1b86f'}
KIND = 'support-replies-app-only'


def requirements(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def preflight(stage, live=LIVE):
    stage, live = stage.resolve(), live.resolve()
    if stage == live or stage in live.parents or live in stage.parents:
        raise ValueError('Staged source must be outside the active application')
    if runtime.fingerprint(stage / 'app') != EXPECTED:
        raise ValueError('Unknown or modified staged application')
    current = runtime.fingerprint(live / 'app')
    if current not in BASELINES | {EXPECTED}:
        raise ValueError('Unknown active application; no changes made')
    if requirements(stage / 'requirements.txt') != requirements(live / 'requirements.txt'):
        raise ValueError('Requirements changed; this installer preserves the existing venv')
    if runtime.run(['systemctl', 'show', UNIT, '-p', 'User', '--value']) not in ('', 'root'):
        raise ValueError('Expected the verified root service')
    if runtime.run(['systemctl', 'show', UNIT, '-p', 'WorkingDirectory', '--value']) != str(live):
        raise ValueError('Unexpected service working directory')
    command = runtime.run(['systemctl', 'show', UNIT, '-p', 'ExecStart', '--value'])
    if str(live / 'venv/bin/python') not in command or 'app.main' not in command:
        raise ValueError('Unexpected ExecStart')
    pid = int(runtime.run(['systemctl', 'show', UNIT, '-p', 'MainPID', '--value']))
    if pid <= 0:
        raise ValueError('Expected an active service')
    env = runtime.service_environment(pid)
    python = live / 'venv/bin/python'
    check = 'import json,sys;print(json.dumps({"version":list(sys.version_info[:3]),"stable":sys.version_info.releaselevel=="final"}))'
    version = json.loads(runtime.run([python, '-I', '-B', '-c', check], env=env))
    if version['version'] < [3, 10, 0] or not version['stable']:
        raise ValueError('A stable Python 3.10+ venv is required')
    runtime.run([python, '-B', '-m', 'pip', 'check'], env=env)
    db = Path(runtime.run([python, '-B', '-c', 'from app.config import config; print(config.db_path)'], cwd=live, env=env))
    if not db.is_absolute():
        db = live / db
    db = db.resolve()
    if not db.is_file():
        raise ValueError('Configured database does not exist')
    return {'old_app': current, 'env': env, 'db': db, 'python': python,
            'venv': str((live / 'venv').resolve())}


def probe(source, live, backup, env, python):
    test_env = {**env, 'DB_PATH': str(backup / 'restore-test.db'), 'LOG_FILE': str(backup / 'probe.log')}
    code = (f'from dotenv import load_dotenv;load_dotenv({str(live / ".env")!r});'
            'import app.main;from app.config import config;from app.db.database import init_db;'
            'init_db(config.db_path)')
    runtime.run([python, '-B', '-c', code], cwd=source, env=test_env)


def stop():
    runtime.run(['systemctl', 'stop', UNIT])
    if runtime.run(['systemctl', 'show', UNIT, '-p', 'MainPID', '--value']) != '0':
        raise RuntimeError('Service stop not confirmed; keep backup for recovery')


def start():
    runtime.run(['systemctl', 'start', UNIT])
    time.sleep(5)
    runtime.run(['systemctl', 'is-active', '--quiet', UNIT])


def restore(backup, live, state):
    # Requires a stopped service; the live database/settings/venv are retained.
    if runtime.fingerprint(backup / 'app') != state['old_app']:
        raise ValueError('Backup application changed')
    if (live / 'app').exists():
        shutil.move(str(live / 'app'), str(backup / ('failed-app-' + str(time.time_ns()))))
    displaced = backup / 'displaced-app'
    if displaced.exists() and runtime.fingerprint(displaced) == state['old_app']:
        shutil.move(str(displaced), str(live / 'app'))
    else:
        shutil.copytree(backup / 'app', live / 'app', symlinks=True)
    state['state'] = 'rolled_back'
    runtime.save_state(backup, state)


def deploy(stage, apply=False, live=LIVE, backup_root=Path('/root/radepa-backups')):
    info = preflight(stage, live)
    if not apply:
        print('PREFLIGHT_OK: application, baseline, requirements and stable runtime verified. NO_CHANGES.')
        return
    if os.geteuid() != 0:
        raise ValueError('Installation requires root')
    if info['old_app'] == EXPECTED:
        runtime.run(['systemctl', 'is-active', '--quiet', UNIT])
        print('ALREADY_CURRENT: support reply application is active.')
        return
    # Account for the existing symlinked venv as well as the live tree.
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    venv_size = sum(p.stat().st_size for p in (live / 'venv').resolve().rglob('*')
                    if p.is_file() and not p.is_symlink())
    if shutil.disk_usage(backup_root).free < 2 * venv_size + info['db'].stat().st_size + 50 * 1024 * 1024:
        raise RuntimeError('Insufficient free space for backup')
    backup = runtime.snapshot(live, info['db'], backup_root)
    state = {'kind': KIND, 'live': str(live), 'db': str(info['db']),
             'old_app': info['old_app'], 'new_app': EXPECTED, 'venv': info['venv'], 'state': 'backed_up'}
    runtime.save_state(backup, state)
    print('BACKUP:', backup, flush=True)
    # Save the exact recovery tools alongside the backup for later rollback.
    (backup / 'tools').mkdir()
    for name in ('install_support_replies.py', 'release_manager.py'):
        shutil.copy2(Path(__file__).with_name(name), backup / 'tools' / name)
    source = backup / 'new-source'
    source.mkdir()
    shutil.copytree(stage / 'app', source / 'app', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if runtime.fingerprint(source / 'app') != EXPECTED:
        raise ValueError('Application changed during preparation; service untouched')
    probe(source, live, backup, info['env'], info['python'])
    try:
        stop()
        if (runtime.fingerprint(live / 'app') != info['old_app']
                or str((live / 'venv').resolve()) != info['venv']):
            raise ValueError('Active application/runtime changed during preparation')
        for name in ('.env', 'requirements.txt'):
            if runtime.digest(live / name) != runtime.digest(backup / name):
                raise ValueError('Settings changed during preparation')
        runtime.copy_db(info['db'], backup / 'bot.db')
        runtime.copy_db(backup / 'bot.db', backup / 'restore-test.db')
        probe(source, live, backup, info['env'], info['python'])
        state['state'] = 'installing'
        runtime.save_state(backup, state)
        shutil.move(str(live / 'app'), str(backup / 'displaced-app'))
        shutil.move(str(source / 'app'), str(live / 'app'))
        if runtime.fingerprint(live / 'app') != EXPECTED:
            raise ValueError('Installed application integrity failure')
        start()
        state['state'] = 'installed'
        runtime.save_state(backup, state)
        print('INSTALL_OK: support reply code is active; verify delivery in Telegram.')
    except BaseException:
        stop()
        if state['state'] == 'installing':
            restore(backup, live, state)
        else:
            state['state'] = 'rolled_back'
            runtime.save_state(backup, state)
        start()
        print('ROLLBACK_OK: previous app active; live database, venv and settings retained. Backup:', backup)
        raise


def rollback(backup, live=LIVE):
    state = json.loads((backup / 'deployment.json').read_text())
    if state.get('kind') != KIND or Path(state['live']) != live or state['state'] == 'rolled_back':
        raise ValueError('Wrong or already restored backup')
    if runtime.fingerprint(backup / 'app') != state['old_app']:
        raise ValueError('Backup application changed')
    current = runtime.fingerprint(live / 'app')
    if current not in (state['old_app'], state['new_app']):
        if state['state'] != 'installing' or not (backup / 'displaced-app').exists():
            raise ValueError('A different app is active; refusing this rollback')
    if str((live / 'venv').resolve()) != state['venv']:
        raise ValueError('Runtime changed; review rollback separately')
    stop()
    runtime.copy_db(Path(state['db']), backup / ('pre-rollback-' + str(time.time_ns()) + '.db'))
    restore(backup, live, state)
    start()
    print('ROLLBACK_OK: previous app active; live database, venv and settings retained.')


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--stage', type=Path)
    mode.add_argument('--rollback', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.rollback and args.apply:
        parser.error('--rollback is a separate action; omit --apply')
    if args.apply or args.rollback:
        if os.geteuid() != 0:
            raise ValueError('Installation/rollback requires root')
        with runtime.deployment_lock():
            if args.rollback:
                rollback(args.rollback.resolve())
            else:
                deploy(args.stage.resolve(), True)
    else:
        deploy(args.stage.resolve())
