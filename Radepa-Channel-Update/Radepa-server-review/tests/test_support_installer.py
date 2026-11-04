"""App-only deployment simulations. SQLite is real and temporary; systemctl is mocked."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('support_installer', ROOT / 'tools/install_support_replies.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SupportInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.live, self.stage = self.root / 'live', self.root / 'stage'
        for path in (self.live, self.stage):
            (path / 'app').mkdir(parents=True)
            (path / 'requirements.txt').write_text('unchanged')
        (self.live / 'app/main.py').write_text('old')
        (self.stage / 'app/main.py').write_text('new')
        (self.stage / 'app/new.py').write_text('module')
        (self.live / '.env').write_text('SYNTHETIC=keep\nPLAYWRIGHT_BROWSERS_PATH=existing-cache\n')
        self.venv = self.root / 'stable-runtime'
        (self.venv / 'bin').mkdir(parents=True)
        (self.venv / 'bin/python').write_text('synthetic executable')
        (self.live / 'venv').symlink_to(self.venv, target_is_directory=True)
        self.db = self.live / 'bot.db'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE balances (credits INTEGER)')
            db.execute('INSERT INTO balances VALUES (7)')
        self.calls = []
        self.active = True
        self.starts = self.probes = 0
        self.fail = False
        self.fail_probe = 0
        self.stable = True
        self.source_hash = installer.runtime.fingerprint(self.stage / 'app')
        self.old_hash = installer.runtime.fingerprint(self.live / 'app')

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, args, **kwargs):
        args = [str(x) for x in args]
        self.calls.append(args)
        if args[0] == 'systemctl':
            if args[1] == 'show':
                return {'User':'root', 'WorkingDirectory':str(self.live),
                        'ExecStart':str(self.live / 'venv/bin/python') + ' -m app.main',
                        'MainPID':'42' if self.active else '0'}[args[args.index('-p') + 1]]
            if args[1] == 'cat':
                return 'synthetic unit'
            if args[1] == 'stop':
                backup = next((self.root / 'backups').iterdir())
                for name in ('app/main.py','.env','venv/bin/python','bot.db','restore-test.db','deployment.json'):
                    self.assertTrue((backup / name).is_file(), name)
                self.active = False
                return ''
            if args[1] == 'start':
                self.starts += 1
                if self.starts == 1:
                    with sqlite3.connect(self.db) as db:
                        db.execute('UPDATE balances SET credits=8')
                    if self.fail:
                        raise RuntimeError('Simulated startup failure')
                self.active = True
                return ''
            if args[1] == 'is-active':
                if not self.active:
                    raise RuntimeError('inactive')
                return ''
        if 'print(config.db_path)' in args[-1]:
            return str(self.db)
        if 'sys.version_info' in args[-1]:
            return json.dumps({'version':[3,10,12], 'stable':self.stable})
        if 'freeze' in args:
            return 'synthetic packages'
        if 'init_db(config.db_path)' in args[-1]:
            self.probes += 1
            self.assertNotEqual(kwargs['env']['DB_PATH'], str(self.db))
            self.assertEqual(kwargs['env']['PLAYWRIGHT_BROWSERS_PATH'], 'existing-cache')
            if self.probes == self.fail_probe:
                raise RuntimeError('Simulated failed migration')
            with sqlite3.connect(kwargs['env']['DB_PATH']) as db:
                db.execute('CREATE TABLE IF NOT EXISTS support_tickets (id TEXT)')
        return ''

    def patches(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(installer, 'EXPECTED', self.source_hash))
        stack.enter_context(patch.object(installer, 'BASELINES', {self.old_hash}))
        stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0))
        stack.enter_context(patch.object(installer.runtime, 'run', side_effect=self.runner))
        stack.enter_context(patch.object(installer.runtime, 'service_environment', return_value={
            'PLAYWRIGHT_BROWSERS_PATH':'existing-cache'}))
        stack.enter_context(patch.object(installer.time, 'sleep'))
        return stack

    def deploy(self, apply=True):
        return installer.deploy(self.stage, apply, self.live, self.root / 'backups')

    def test_default_is_readonly_and_does_not_create_backups(self):
        with self.patches():
            self.deploy(False)
        self.assertFalse((self.root / 'backups').exists())
        self.assertFalse(any(c[:2] == ['systemctl','stop'] for c in self.calls))
        self.assertEqual(installer.runtime.fingerprint(self.live / 'app'), self.old_hash)

    def test_success_keeps_existing_runtime_settings_and_takes_verified_backup(self):
        env = (self.live / '.env').read_bytes()
        with self.patches():
            self.deploy()
        self.assertEqual((self.live / '.env').read_bytes(), env)
        self.assertEqual((self.live / 'venv').resolve(), self.venv)
        self.assertEqual(installer.runtime.fingerprint(self.live / 'app'), self.source_hash)
        self.assertTrue(self.active)
        self.assertEqual(self.probes, 2)
        backup = next((self.root / 'backups').iterdir())
        self.assertTrue((backup / 'tools/install_support_replies.py').is_file())
        with sqlite3.connect(backup / 'bot.db') as db:
            self.assertEqual(db.execute('SELECT credits FROM balances').fetchone(), (7,))

    def test_failure_restores_app_without_erasing_new_payments(self):
        self.fail = True
        with self.patches(), self.assertRaises(RuntimeError):
            self.deploy()
        self.assertTrue(self.active)
        self.assertEqual(installer.runtime.fingerprint(self.live / 'app'), self.old_hash)
        self.assertEqual((self.live / 'venv').resolve(), self.venv)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT credits FROM balances').fetchone(), (8,))

    def test_failed_migration_probe_does_not_stop_service(self):
        self.fail_probe = 1
        with self.patches(), self.assertRaises(RuntimeError):
            self.deploy()
        self.assertFalse(any(c[:2] == ['systemctl','stop'] for c in self.calls))

    def test_failed_latest_migration_probe_restarts_old_app(self):
        self.fail_probe = 2
        with self.patches(), self.assertRaises(RuntimeError):
            self.deploy()
        self.assertTrue(self.active)
        self.assertEqual(installer.runtime.fingerprint(self.live / 'app'), self.old_hash)

    def test_failed_snapshot_cannot_stop_service(self):
        with self.patches(), patch.object(installer.runtime,'snapshot',side_effect=OSError('disk')), self.assertRaises(OSError):
            self.deploy()
        self.assertFalse(any(c[:2] == ['systemctl','stop'] for c in self.calls))

    def test_unknown_or_changed_source_is_rejected(self):
        with self.patches(), patch.object(installer,'BASELINES',set()), self.assertRaises(ValueError):
            self.deploy()
        self.assertEqual(self.calls, [])
        (self.stage / 'app/new.py').write_text('changed')
        with self.patches(), self.assertRaises(ValueError):
            self.deploy()
        self.assertFalse((self.root / 'backups').exists())

    def test_changed_requirements_are_rejected(self):
        (self.stage / 'requirements.txt').write_text('different')
        with self.patches(), self.assertRaises(ValueError):
            self.deploy()
        self.assertEqual(self.calls, [])

    def test_prerelease_runtime_is_rejected(self):
        self.stable = False
        with self.patches(), self.assertRaises(ValueError):
            self.deploy()
        self.assertFalse((self.root / 'backups').exists())

    def test_repeat_installation_is_a_noop(self):
        with self.patches():
            self.deploy()
            self.calls.clear()
            self.deploy()
        self.assertFalse(any(c[:2] == ['systemctl','stop'] for c in self.calls))
        self.assertEqual(len(list((self.root / 'backups').iterdir())), 1)

    def test_manual_rollback_keeps_latest_data_and_unchanged_runtime(self):
        with self.patches():
            self.deploy()
            backup = next((self.root / 'backups').iterdir())
            with sqlite3.connect(self.db) as db:
                db.execute('UPDATE balances SET credits=9')
            installer.rollback(backup, self.live)
        self.assertEqual(installer.runtime.fingerprint(self.live / 'app'), self.old_hash)
        self.assertEqual((self.live / 'venv').resolve(), self.venv)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT credits FROM balances').fetchone(), (9,))

    def test_old_rollback_cannot_replace_another_version(self):
        with self.patches():
            self.deploy()
            backup = next((self.root / 'backups').iterdir())
            (self.live / 'app/main.py').write_text('another deployment')
            self.calls.clear()
            with self.assertRaises(ValueError):
                installer.rollback(backup, self.live)
        self.assertFalse(any(c[:2] == ['systemctl','stop'] for c in self.calls))
