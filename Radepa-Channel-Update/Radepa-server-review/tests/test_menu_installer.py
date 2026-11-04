"""Check the new wrapper keeps deployment opt-in and recovery delegated to the tested engine."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'tools/install_telegram_menu.py'
spec=importlib.util.spec_from_file_location('menu_installer',path)
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class MenuInstallerTests(unittest.TestCase):
    def setUp(self):
        self.original_umask=os.umask(0o077)

    def tearDown(self):
        os.umask(self.original_umask)

    def test_default_only_preflights_without_a_deployment_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('sys.argv',['installer','--stage',temp]),patch.object(installer.engine,'deploy') as deploy,patch.object(installer.engine.runtime,'deployment_lock') as lock:
                installer.main()
            deploy.assert_called_once_with(Path(temp).resolve())
            lock.assert_not_called()

    def test_apply_is_explicit_and_locked(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('sys.argv',['installer','--stage',temp,'--apply']),patch.object(installer.engine,'deploy') as deploy,patch.object(installer.engine.os,'geteuid',return_value=0),patch.object(installer.engine.runtime,'deployment_lock',return_value=nullcontext()) as lock:
                installer.main()
            deploy.assert_called_once_with(Path(temp).resolve(),True)
            lock.assert_called_once()

    def test_nonroot_apply_cannot_deploy(self):
        with patch('sys.argv',['installer','--stage','/tmp/source','--apply']),patch.object(installer.engine.os,'geteuid',return_value=1000),patch.object(installer.engine,'deploy') as deploy:
            with self.assertRaises(ValueError):installer.main()
        deploy.assert_not_called()

    def test_rollback_uses_same_locked_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('sys.argv',['installer','--rollback',temp]),patch.object(installer.engine,'rollback') as rollback,patch.object(installer.engine.os,'geteuid',return_value=0),patch.object(installer.engine.runtime,'deployment_lock',return_value=nullcontext()):
                installer.main()
            rollback.assert_called_once_with(Path(temp).resolve())
