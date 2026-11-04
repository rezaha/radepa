"""Installer rollback tests with SQLite and simulated systemctl; no live services."""
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('receipt_installer', Path(__file__).resolve().parents[1] / 'tools/install_receipt_review.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ReceiptInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.live, self.stage = self.root/'live', self.root/'stage'
        for path in (self.live, self.stage):
            (path/'app').mkdir(parents=True)
            (path/'requirements.txt').write_text('unchanged')
        (self.live/'app/main.py').write_text('old code')
        (self.stage/'app/main.py').write_text('new code')
        (self.stage/'app/new.py').write_text('new module')
        (self.live/'.env').write_text('SYNTHETIC=test')
        self.db=self.live/'bot.db'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE balances (credits INTEGER)')
            db.execute('INSERT INTO balances VALUES (7)')
        self.active=True
        self.starts=0
        self.fail=False
        self.calls=[]

    def tearDown(self):
        self.temp.cleanup()

    def fake_run(self, args, **kwargs):
        args=[str(x) for x in args];self.calls.append(args)
        if args[0]!='systemctl':
            if 'print(config.db_path)' in args[-1]: return str(self.db)
            # Preflight must be pointed at the verified restored copy, not live DB.
            self.assertNotEqual(kwargs['env']['DB_PATH'],str(self.db))
            with sqlite3.connect(kwargs['env']['DB_PATH']) as db:
                self.assertEqual(db.execute('SELECT credits FROM balances').fetchone(),(7,))
            return ''
        if args[1]=='show':
            return {'User':'root','WorkingDirectory':str(self.live),'MainPID':'42' if self.active else '0'}[args[args.index('-p')+1]]
        if args[1]=='stop': self.active=False;return ''
        if args[1]=='start':
            self.starts+=1
            if self.starts==1:
                # A new payment happened before a crash; rollback must preserve it.
                with sqlite3.connect(self.db) as db:db.execute('UPDATE balances SET credits=8')
                if self.fail:raise RuntimeError('Simulated startup failure')
            self.active=True;return ''
        if args[1]=='is-active':
            if not self.active:raise RuntimeError('Inactive')
            return ''
        raise AssertionError(args)

    def deploy(self):
        with patch.object(installer.os,'geteuid',return_value=0), patch.object(installer,'runtime_environment',return_value={}), patch.object(installer,'run',side_effect=self.fake_run), patch.object(installer.time,'sleep'), patch.object(installer,'EXPECTED',installer.fingerprint(self.stage/'app')), patch.object(installer,'BASELINES',{installer.fingerprint(self.live/'app')}):
            installer.deploy(self.stage,self.live,self.root/'backups')

    def test_success_preserves_settings_and_database_and_saves_valid_backup(self):
        self.deploy()
        self.assertTrue(self.active)
        self.assertEqual((self.live/'app/main.py').read_text(),'new code')
        self.assertEqual((self.live/'.env').read_text(),'SYNTHETIC=test')
        backup=next((self.root/'backups').iterdir())
        with sqlite3.connect(backup/'bot.db') as db:
            self.assertEqual(db.execute('SELECT credits FROM balances').fetchone(),(7,))

    def test_failed_start_restores_code_without_losing_newer_payment(self):
        self.fail=True
        with self.assertRaises(RuntimeError):self.deploy()
        self.assertTrue(self.active)
        self.assertEqual((self.live/'app/main.py').read_text(),'old code')
        self.assertFalse((self.live/'app/new.py').exists())
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT credits FROM balances').fetchone(),(8,))

    def test_unknown_source_is_rejected_before_any_service_action(self):
        with patch.object(installer.os,'geteuid',return_value=0), patch.object(installer,'EXPECTED',installer.fingerprint(self.stage/'app')), patch.object(installer,'run') as runner:
            with self.assertRaises(RuntimeError):installer.deploy(self.stage,self.live,self.root/'backups')
        runner.assert_not_called()
        self.assertFalse((self.root/'backups').exists())
