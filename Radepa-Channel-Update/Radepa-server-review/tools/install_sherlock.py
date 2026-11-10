"""Guarded Sherlock app-only install; default preflight never stops the service.

Preserves settings, SQLite and the active bot venv. Optional CLI installation and
feature activation are separate steps. The feature defaults to disabled.
"""
import importlib.util
from pathlib import Path

path = Path(__file__).with_name('install_support_replies.py')
spec = importlib.util.spec_from_file_location('sherlock_install_engine', path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
engine.EXPECTED = '8a47844b98274caaf37b94d92b981223da31a46b2089ce30dd1f118b2dec64c2'
engine.BASELINES = {'2d6225790c6d177a9f11fe52ecf66b7523a1408e0819752a6fe7a9427d3e40fa'}
engine.KIND = 'sherlock-app-only'
engine.FEATURE_LABEL = 'Sherlock (enable separately in settings)'
engine.RECOVERY_TOOLS += ('install_sherlock.py',)
engine.__doc__ = __doc__


def main():
    engine.main()


if __name__ == '__main__':
    main()
