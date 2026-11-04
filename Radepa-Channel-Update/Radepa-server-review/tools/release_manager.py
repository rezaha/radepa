"""Verified release staging, explicit deployment and code-only rollback.
No command starts a staging polling bot. Production deployment requires --apply.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

LIVE = Path('/opt/radepa')
UNIT = 'radepa.service'
RELEASES = Path('/opt/radepa-releases')
BASELINES = {
    '8c47d5b1f33c054634f0cb38c277e6eb6d0d905d8485fdef9bb8c97bf45d6aae',
    '48758402df33524ddb829959fd4a0a539bcb9ca55717ffeeeef6ad1a22c639e7',
    '4fd9a784fad76896dbc783678610720856364b1ce8e1d9e467bdf8898d5a3874',
}
APP_KEYS = ('BOT_TOKEN','ADMIN_IDS','PAYMENT_CARD_NUMBER','PAYMENT_CARD_HOLDER','SERPER_API_KEY',
            'SERPAPI_KEY','SERPAPI_KEY_2','GOOGLE_API_KEY','GOOGLE_CSE_ID','ABSTRACT_API_KEY',
            'DB_PATH','LOG_FILE','TELEGRAM_PROXY_URL','INSTAGRAM_INSPECT_BROWSER_PATH')


@contextmanager
def deployment_lock(path=Path('/run/lock/radepa-release.lock')):
    with path.open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another deployment or rollback is running') from None
        try:
            yield
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(folder):
    h = hashlib.sha256()
    for p in sorted(folder.rglob('*')):
        if p.is_file() and p.suffix in ('.py','.sql'):
            if p.is_symlink(): raise ValueError('Source symlink')
            h.update((p.relative_to(folder).as_posix()+' '+hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()+'\n').encode())
    return h.hexdigest()


def verify(source):
    manifest = json.loads((source/'release-manifest.json').read_text())
    if manifest.get('format') != 1 or not manifest.get('files'): raise ValueError('Invalid manifest')
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or (relative.parts[0] not in ('app','tests','tools','docs','release','requirements.txt') and not (len(relative.parts)==1 and relative.suffix=='.md')):
            raise ValueError('Unsafe manifest path')
        path = source/relative
        if path.resolve() != path.absolute() or not path.is_file() or digest(path) != expected:
            raise ValueError('Release file missing, changed or symlinked: '+name)
    for folder in ('app','tests','tools','docs','release'):
        for path in (source/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and path.relative_to(source).as_posix() not in manifest['files']:
                raise ValueError('Unexpected release file')
    if (source/'.env').exists(): raise ValueError('Settings must not be packaged')
    return manifest


def run(args, cwd=None, env=None, log=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, text=True)
    if log:
        log.write_text(result.stdout+'\n'+result.stderr)
        log.chmod(0o600)
    if result.returncode: raise RuntimeError('Command failed; see private stage log if supplied')
    return result.stdout.strip()


def isolated_env(stage):
    env = {k:v for k,v in os.environ.items() if k not in APP_KEYS}
    env.update({'BOT_TOKEN':'123456:offline-test-token','ADMIN_IDS':'999','PAYMENT_CARD_NUMBER':'test',
                'PAYMENT_CARD_HOLDER':'test','SERPER_API_KEY':'offline-test-key','ABSTRACT_API_KEY':'',
                'SERPAPI_KEY':'','SERPAPI_KEY_2':'','GOOGLE_API_KEY':'','GOOGLE_CSE_ID':'',
                'DB_PATH':str(stage/'state/bot.db'),'LOG_FILE':str(stage/'state/bot.log'),
                'TELEGRAM_PROXY_URL':'','PYTHONDONTWRITEBYTECODE':'1',
                'PLAYWRIGHT_BROWSERS_PATH':str(stage/'browsers')})
    return env


def stage_release(source, root, browser=True):
    if sys.version_info < (3,10): raise ValueError('Python 3.10 or newer required')
    source, root = source.resolve(), root.resolve()
    if root == LIVE or root.is_relative_to(LIVE) or LIVE.is_relative_to(root):
        raise ValueError('Stage must not overlap production')
    manifest = verify(source)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='radepa-',dir=root))
    target = stage/'source'; target.mkdir()
    for name in manifest['files']:
        destination = target/name; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,destination)
    shutil.copy2(source/'release-manifest.json',target/'release-manifest.json')
    env = isolated_env(stage)
    python = stage/'venv/bin/python'
    run([sys.executable,'-m','venv',stage/'venv'], log=stage/'venv.log')
    run([python,'-m','pip','install','-r',target/'requirements.txt'],env=env,log=stage/'install.log')
    run([python,'-m','pip','check'],env=env,log=stage/'pip-check.log')
    if browser:
        run([python,'-m','playwright','install','chromium'],env=env,log=stage/'browser-install.log')
    args = [python,'-B',target/'tools/release_smoke.py','--work',stage/'state','--tests']
    if browser: args.append('--browser')
    run(args,cwd=target,env=env,log=stage/'smoke.log')
    verify(target)
    ready={'manifest_sha256':digest(target/'release-manifest.json'),'app':fingerprint(target/'app'),
           'browser':browser,'python':run([python,'--version']),
           'packages':run([python,'-m','pip','freeze'],env=env)}
    (stage/'ready.json').write_text(json.dumps(ready,indent=2))
    print('STAGE_READY:',stage,'browser:',browser)
    return stage


def check_stage(stage):
    stage=stage.resolve(); source=stage/'source'
    verify(source)
    ready=json.loads((stage/'ready.json').read_text())
    if ready['manifest_sha256']!=digest(source/'release-manifest.json') or ready['app']!=fingerprint(source/'app'):
        raise ValueError('Stage changed since validation')
    if not ready['browser']: raise ValueError('Browser check is required before deployment')
    if run([stage/'venv/bin/python','-m','pip','freeze'],env=isolated_env(stage))!=ready['packages']:
        raise ValueError('Stage dependencies changed')
    return source, ready


def service_environment(pid):
    env=dict(item.split('=',1) for item in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in item)
    env['PYTHONDONTWRITEBYTECODE']='1'
    return env


def copy_db(source,target):
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]: raise RuntimeError('SQLite integrity failure')


def snapshot(live, db, backup_root):
    backup_root.mkdir(mode=0o700,parents=True,exist_ok=True)
    size=sum(p.stat().st_size for p in live.rglob('*') if p.is_file() and not p.is_symlink())
    if shutil.disk_usage(backup_root).free < 2*size+db.stat().st_size+50*1024*1024:
        raise RuntimeError('Insufficient free space for verified backup')
    backup=Path(tempfile.mkdtemp(prefix='inspector-',dir=backup_root))
    shutil.copytree(live/'app',backup/'app',symlinks=True)
    shutil.copytree(live/'venv',backup/'venv',symlinks=True)
    run([backup/'venv/bin/python','-m','pip','check'])
    for name in ('.env','requirements.txt'):
        shutil.copy2(live/name,backup/name)
        if digest(live/name)!=digest(backup/name): raise RuntimeError('Settings backup mismatch')
    if fingerprint(live/'app')!=fingerprint(backup/'app'): raise RuntimeError('Code backup mismatch')
    copy_db(db,backup/'bot.db');copy_db(backup/'bot.db',backup/'restore-test.db')
    (backup/'service-unit.txt').write_text(run(['systemctl','cat',UNIT]))
    (backup/'packages.txt').write_text(run([live/'venv/bin/python','-m','pip','freeze']))
    return backup


def save_state(backup,state):
    temporary=backup/'deployment.json.tmp'
    with temporary.open('w') as f:
        json.dump(state,f,indent=2);f.flush();os.fsync(f.fileno())
    temporary.replace(backup/'deployment.json')


def restore(backup,live,state):
    # Service must be stopped. Do not restore SQLite automatically.
    for name in ('app','venv'):
        old=backup/('displaced-'+name)
        current=live/name
        fallback=False
        if old.is_symlink() and not old.exists():
            fallback=True  # Original release directory was removed; use verified full snapshot.
        elif not old.exists() and not old.is_symlink():
            fallback=(name=='app' and fingerprint(current)!=state['old_app']) or (
                name=='venv' and current.is_symlink() and current.resolve()==(Path(state['stage'])/'venv').resolve())
            if not fallback:continue
        if current.exists() or current.is_symlink():
            shutil.move(str(current),str(backup/('failed-'+name+'-'+str(time.time_ns()))))
        if fallback:
            shutil.copytree(backup/name,current,symlinks=True)
        else:
            shutil.move(str(old),str(current))
    for name in ('.env','requirements.txt'):shutil.copy2(backup/name,live/name)
    state['state']='rolled_back';save_state(backup,state)


def rollback(backup,live=LIVE):
    state=json.loads((backup/'deployment.json').read_text())
    if Path(state['live'])!=live or state['state']=='rolled_back': raise ValueError('Invalid or already restored backup')
    if fingerprint(backup/'app') != state['old_app']: raise ValueError('Backup code changed')
    if fingerprint(live/'app') not in (state['new_app'],state['old_app']):
        if state['state']!='installing' or not (backup/'displaced-app').exists():
            raise ValueError('A different deployment is active; refusing old rollback')
    run(['systemctl','stop',UNIT])
    if run(['systemctl','show',UNIT,'-p','MainPID','--value'])!='0':raise RuntimeError('Stop failed')
    copy_db(Path(state['db']),backup/('pre-rollback-'+str(time.time_ns())+'.db'))
    restore(backup,live,state)
    run(['systemctl','start',UNIT]);time.sleep(3)
    run(['systemctl','is-active','--quiet',UNIT])
    print('ROLLBACK_OK: previous code and environment restored; live database retained.')


def deploy(stage,apply=False,live=LIVE,backup_root=Path('/root/radepa-backups'),releases=RELEASES):
    source, ready=check_stage(stage)
    if not apply:
        print('PLAN_ONLY: no production files, service or database changed.')
        return
    if os.geteuid()!=0:raise ValueError('Deployment requires root')
    if not stage.resolve().is_relative_to(releases.resolve()):
        raise ValueError('Deployable staging must be retained under /opt/radepa-releases')
    old=fingerprint(live/'app')
    if old==ready['app'] and (live/'venv').resolve()==(stage/'venv').resolve():
        run(['systemctl','is-active','--quiet',UNIT])
        print('ALREADY_CURRENT: validated release is already active.')
        return
    if old not in BASELINES:raise ValueError('Unknown production source; review drift first')
    if run(['systemctl','show',UNIT,'-p','User','--value']) not in ('root',''):
        raise ValueError('This installer supports the verified root service only')
    if run(['systemctl','show',UNIT,'-p','WorkingDirectory','--value'])!=str(live):raise ValueError('Unexpected working directory')
    command=run(['systemctl','show',UNIT,'-p','ExecStart','--value'])
    if str(live/'venv/bin/python') not in command or 'app.main' not in command:raise ValueError('Unexpected ExecStart')
    pid=int(run(['systemctl','show',UNIT,'-p','MainPID','--value']))
    if pid<=0:raise ValueError('Expected an active production service')
    env=service_environment(pid)
    if 'PLAYWRIGHT_BROWSERS_PATH' in env:raise ValueError('Review existing service browser path before deployment')
    db=Path(run([live/'venv/bin/python','-B','-c','from app.config import config; print(config.db_path)'],cwd=live,env=env))
    if not db.is_absolute():db=live/db
    db=db.resolve()
    if not db.is_file():raise ValueError('Configured database missing')
    # Full validated backup exists before even stopping the service.
    backup=snapshot(live,db,backup_root)
    state={'live':str(live),'stage':str(stage),'db':str(db),'old_app':old,'new_app':ready['app'],'state':'backed_up'}
    save_state(backup,state);print('BACKUP:',backup,flush=True)
    try:
        run(['systemctl','stop',UNIT])
        if run(['systemctl','show',UNIT,'-p','MainPID','--value'])!='0':raise RuntimeError('Stop failed')
        if fingerprint(live/'app')!=old:raise ValueError('Source changed during backup')
        copy_db(db,backup/'bot.db');copy_db(backup/'bot.db',backup/'restore-test.db')
        # Probe migration on a restore copy using production configuration, without polling.
        probe={**env,'DB_PATH':str(backup/'restore-test.db'),'LOG_FILE':str(backup/'probe.log')}
        code=f'from dotenv import load_dotenv;load_dotenv({str(live/".env")!r});import app.main;from app.config import config;from app.db.database import init_db;init_db(config.db_path)'
        run([stage/'venv/bin/python','-B','-c',code],cwd=source,env=probe)
        state['state']='installing';save_state(backup,state)
        for name in ('app','venv'):
            shutil.move(str(live/name),str(backup/('displaced-'+name)))
            if name=='app':shutil.copytree(source/'app',live/'app')
            else:(live/'venv').symlink_to(stage/'venv',target_is_directory=True)
        shutil.copy2(source/'requirements.txt',live/'requirements.txt')
        run([stage/'venv/bin/python','-c',
             'import sys;from dotenv import set_key;set_key(sys.argv[1],"PLAYWRIGHT_BROWSERS_PATH",sys.argv[2])',
             live/'.env',stage/'browsers'])
        run(['systemctl','start',UNIT]);time.sleep(5)
        run(['systemctl','is-active','--quiet',UNIT])
        state['state']='installed';save_state(backup,state)
        print('INSTALL_OK: process active; functional Telegram acceptance is still required.')
    except BaseException:
        run(['systemctl','stop',UNIT])
        if run(['systemctl','show',UNIT,'-p','MainPID','--value'])!='0':raise RuntimeError('Rollback stop failed; backup retained')
        restore(backup,live,state)
        run(['systemctl','start',UNIT]);time.sleep(3)
        run(['systemctl','is-active','--quiet',UNIT])
        print('ROLLBACK_OK: code restored; live database retained. Backup:',backup)
        raise


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    stage=sub.add_parser('stage');stage.add_argument('--source',required=True,type=Path)
    stage.add_argument('--root',type=Path,default=RELEASES);stage.add_argument('--without-browser',action='store_true')
    install=sub.add_parser('deploy');install.add_argument('--stage',required=True,type=Path);install.add_argument('--apply',action='store_true')
    back=sub.add_parser('rollback');back.add_argument('--backup',required=True,type=Path)
    args=parser.parse_args()
    if args.command=='stage':stage_release(args.source.resolve(),args.root,not args.without_browser)
    elif args.command=='deploy':
        if args.apply:
            if os.geteuid()!=0:raise ValueError('Deployment requires root')
            with deployment_lock():deploy(args.stage.resolve(),True)
        else:deploy(args.stage.resolve(),False)
    else:
        if os.geteuid()!=0:raise ValueError('Rollback requires root')
        with deployment_lock():rollback(args.backup.resolve())
