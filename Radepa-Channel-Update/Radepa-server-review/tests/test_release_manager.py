"""Release validation and deployment simulations; no real service or production paths."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

manager=load('release_manager')
builder=load('build_release')


def manifest(source):
    files={p.relative_to(source).as_posix():manager.digest(p) for p in source.rglob('*') if p.is_file()}
    (source/'release-manifest.json').write_text(json.dumps({'format':1,'source_commit':'0'*40,'files':files}))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.live=self.root/'live';self.stage=self.root/'releases'/'test';self.source=self.stage/'source'
        for folder in (self.live,self.source):
            (folder/'app').mkdir(parents=True);(folder/'requirements.txt').write_text('test')
        (self.live/'app/main.py').write_text('old')
        (self.source/'app/main.py').write_text('new')
        (self.source/'tools').mkdir();(self.source/'tools/release_smoke.py').write_text('# fixture')
        manifest(self.source)
        for folder in (self.live,self.stage):
            (folder/'venv/bin').mkdir(parents=True);(folder/'venv/bin/python').write_text('fixture')
        (self.stage/'browsers').mkdir()
        (self.live/'.env').write_text('SETTINGS=original')
        self.db=self.live/'bot.db'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE users (credits INTEGER)');db.execute('INSERT INTO users VALUES (7)')
        self.old=manager.fingerprint(self.live/'app')
        self.ready={'manifest_sha256':manager.digest(self.source/'release-manifest.json'),'app':manager.fingerprint(self.source/'app'),'browser':True,'packages':'packages'}
        (self.stage/'ready.json').write_text(json.dumps(self.ready))
        self.calls=[];self.active=True;self.starts=0;self.fail=False

    def tearDown(self):self.temp.cleanup()

    def runner(self,args,**kwargs):
        args=[str(x) for x in args];self.calls.append(args)
        if args[0]=='systemctl':
            if args[1]=='show':return {'User':'root','WorkingDirectory':str(self.live),'MainPID':'42' if self.active else '0','ExecStart':str(self.live/'venv/bin/python')+' -m app.main'}[args[args.index('-p')+1]]
            if args[1]=='cat':return 'service fixture'
            if args[1]=='stop':
                backup=next((self.root/'backups').iterdir())
                for name in ('app/main.py','.env','venv/bin/python','bot.db','restore-test.db','deployment.json'):
                    self.assertTrue((backup/name).exists(),name)
                self.active=False;return ''
            if args[1]=='start':
                self.starts+=1
                if self.starts==1:
                    with sqlite3.connect(self.db) as db:db.execute('UPDATE users SET credits=8')
                    if self.fail:raise RuntimeError('Simulated failed start')
                self.active=True;return ''
            if args[1]=='is-active':
                if not self.active:raise RuntimeError('inactive')
                return ''
        if 'print(config.db_path)' in args[-1]:return str(self.db)
        if 'freeze' in args:return 'packages'
        if any('set_key' in a for a in args):(self.live/'.env').write_text('SETTINGS=original\nPLAYWRIGHT_BROWSERS_PATH=stage')
        return ''

    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(manager,'run',side_effect=self.runner))
        stack.enter_context(patch.object(manager,'service_environment',return_value={}))
        stack.enter_context(patch.object(manager,'BASELINES',{self.old}))
        stack.enter_context(patch.object(manager.os,'geteuid',return_value=0))
        stack.enter_context(patch.object(manager.time,'sleep'))
        return stack

    def apply(self):
        return manager.deploy(self.stage,True,self.live,self.root/'backups',self.root/'releases')

    def test_default_plan_never_touches_service_or_production(self):
        with self.patches():manager.deploy(self.stage,live=self.live)
        self.assertFalse(any(c[0]=='systemctl' for c in self.calls))
        self.assertFalse((self.root/'backups').exists())
        self.assertEqual((self.live/'app/main.py').read_text(),'old')

    def test_deploy_backs_up_everything_before_stop_and_uses_validated_venv(self):
        with self.patches():self.apply()
        self.assertTrue(self.active)
        self.assertTrue((self.live/'venv').is_symlink())
        self.assertEqual((self.live/'app/main.py').read_text(),'new')
        backup=next((self.root/'backups').iterdir())
        self.assertEqual((backup/'.env').read_text(),'SETTINGS=original')
        self.assertTrue((backup/'venv/bin/python').is_file())
        with sqlite3.connect(backup/'restore-test.db') as db:self.assertEqual(db.execute('SELECT credits FROM users').fetchone(),(7,))
        self.assertEqual(json.loads((backup/'deployment.json').read_text())['state'],'installed')

    def test_failure_rolls_back_code_settings_and_venv_but_retains_new_payments(self):
        self.fail=True
        with self.patches(),self.assertRaises(RuntimeError):self.apply()
        self.assertTrue(self.active)
        self.assertEqual((self.live/'app/main.py').read_text(),'old')
        self.assertFalse((self.live/'venv').is_symlink())
        self.assertEqual((self.live/'.env').read_text(),'SETTINGS=original')
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT credits FROM users').fetchone(),(8,))

    def test_failed_backup_cannot_stop_service_or_change_code(self):
        with self.patches(),patch.object(manager,'snapshot',side_effect=OSError('disk full')),self.assertRaises(OSError):self.apply()
        self.assertFalse(any(c[:2]==['systemctl','stop'] for c in self.calls))
        self.assertEqual((self.live/'app/main.py').read_text(),'old')

    def test_unknown_production_code_aborts_before_backup(self):
        with self.patches(),patch.object(manager,'BASELINES',set()),self.assertRaises(ValueError):self.apply()
        self.assertFalse((self.root/'backups').exists())

    def test_manual_rollback_keeps_latest_database(self):
        with self.patches():
            self.apply();backup=next((self.root/'backups').iterdir())
            with sqlite3.connect(self.db) as db:db.execute('UPDATE users SET credits=12')
            manager.rollback(backup,self.live)
        self.assertEqual((self.live/'app/main.py').read_text(),'old')
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT credits FROM users').fetchone(),(12,))

    def test_changed_stage_source_or_dependencies_rejected(self):
        (self.source/'app/main.py').write_text('tampered')
        with self.assertRaises(ValueError):manager.verify(self.source)

    def test_no_browser_stage_is_not_deployable(self):
        self.ready['browser']=False;(self.stage/'ready.json').write_text(json.dumps(self.ready))
        with self.patches(),self.assertRaises(ValueError):self.apply()
        self.assertFalse(any(c[0]=='systemctl' for c in self.calls))

    def test_staging_refuses_production_path_before_creating_anything(self):
        with patch.object(manager,'LIVE',self.live),self.assertRaises(ValueError):
            manager.stage_release(self.source,self.live/'stage')

    def test_stage_environment_cannot_reuse_exported_production_credentials(self):
        with patch.dict(os.environ,{'BOT_TOKEN':'real','ABSTRACT_API_KEY':'real','DB_PATH':'production.db'}):
            env=manager.isolated_env(self.stage)
        self.assertEqual(env['ABSTRACT_API_KEY'],'')
        self.assertNotEqual(env['BOT_TOKEN'],'real')
        self.assertNotEqual(env['DB_PATH'],'production.db')

    def test_manifest_path_traversal_is_rejected(self):
        (self.source/'release-manifest.json').write_text(json.dumps({'format':1,'files':{'../../escape.py':'0'}}))
        with self.assertRaises(ValueError):manager.verify(self.source)

    def test_bundle_excludes_keys_databases_and_untracked_files(self):
        import zipfile
        (self.source/'.env').write_text('SECRET=never-package')
        (self.source/'users.db').write_text('private')
        (self.source/'untracked.py').write_text('private')
        tracked=b'app/main.py\0requirements.txt\0.env\0users.db\0tools/release_smoke.py\0'
        def git(args,**kwargs):
            if 'status' in args:return b''
            if 'ls-files' in args:return tracked
            return '0'*40+'\n'
        output=self.root/'bundle.zip'
        with patch.object(builder.subprocess,'check_output',side_effect=git):builder.build(output,self.source)
        with zipfile.ZipFile(output) as archive:
            names=archive.namelist()
            self.assertNotIn('radepa-release/.env',names)
            self.assertNotIn('radepa-release/users.db',names)
            self.assertNotIn('radepa-release/untracked.py',names)
            self.assertIn('radepa-release/app/main.py',names)

    def test_concurrent_deployment_lock_is_rejected(self):
        lock=self.root/'deployment.lock'
        with manager.deployment_lock(lock):
            with self.assertRaises(RuntimeError):
                with manager.deployment_lock(lock):pass
        with manager.deployment_lock(lock):pass

    def test_interrupted_partial_copy_can_be_recovered_without_losing_database(self):
        backup_root=self.root/'backups'
        with self.patches():
            backup=manager.snapshot(self.live,self.db,backup_root)
            state={'live':str(self.live),'stage':str(self.stage),'db':str(self.db),'old_app':self.old,'new_app':self.ready['app'],'state':'installing'}
            manager.save_state(backup,state)
            shutil.move(str(self.live/'app'),str(backup/'displaced-app'))
            (self.live/'app').mkdir();(self.live/'app/partial.py').write_text('partial')
            manager.rollback(backup,self.live)
        self.assertEqual((self.live/'app/main.py').read_text(),'old')
        self.assertFalse((self.live/'app/partial.py').exists())

    def test_repeat_deploy_is_nonmutating(self):
        with self.patches():
            self.apply();self.calls.clear();self.apply()
        self.assertFalse(any(c[:2]==['systemctl','stop'] for c in self.calls))
        self.assertEqual(len(list((self.root/'backups').iterdir())),1)

    def test_tehran_timezone_works_without_operating_system_tz_database(self):
        import zoneinfo
        original=zoneinfo.TZPATH
        try:
            zoneinfo.reset_tzpath(())
            zone=zoneinfo.ZoneInfo.no_cache('Asia/Tehran')
            self.assertEqual(zone.key,'Asia/Tehran')
        finally:
            zoneinfo.reset_tzpath(original)

    def test_rollback_can_use_verified_snapshot_if_displaced_files_were_lost(self):
        with self.patches():
            self.apply();backup=next((self.root/'backups').iterdir())
            shutil.rmtree(backup/'displaced-app')
            shutil.rmtree(backup/'displaced-venv')
            manager.rollback(backup,self.live)
        self.assertEqual((self.live/'app/main.py').read_text(),'old')
        self.assertFalse((self.live/'venv').is_symlink())

    def test_standalone_smoke_refuses_production_state_directory(self):
        smoke=load('release_smoke')
        with self.assertRaises(ValueError):smoke.check(Path('/opt/radepa/data'))
