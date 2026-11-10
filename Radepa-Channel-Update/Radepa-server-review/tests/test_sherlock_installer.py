"""Sherlock-specific app-only deployment simulations, never real systemctl."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import test_support_installer as base

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sherlock_installer', ROOT/'tools/install_sherlock.py')
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class SherlockInstallerTests(base.SupportInstallerTests):
    def setUp(self):
        swap = patch.object(base, 'installer', wrapper.engine)
        swap.start()
        self.addCleanup(swap.stop)
        super().setUp()

    def test_checked_in_app_matches_expected_fingerprint(self):
        self.assertEqual(wrapper.engine.runtime.fingerprint(ROOT/'app'), wrapper.engine.EXPECTED)
        self.assertEqual(wrapper.engine.BASELINES, {'2d6225790c6d177a9f11fe52ecf66b7523a1408e0819752a6fe7a9427d3e40fa'})

    def test_backup_contains_standalone_matching_rollback_wrapper(self):
        with self.patches():
            self.deploy()
        backup = next((self.root/'backups').iterdir())
        for name in wrapper.engine.RECOVERY_TOOLS:
            self.assertEqual((backup/'tools'/name).read_bytes(), (ROOT/'tools'/name).read_bytes())
        with self.patches():
            wrapper.engine.rollback(backup, self.live)
        self.assertTrue(self.active)
        self.assertEqual(wrapper.engine.runtime.fingerprint(self.live/'app'), self.old_hash)
