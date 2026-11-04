"""App-only native Menu update; read-only preflight unless --apply is supplied."""
import importlib.util
from pathlib import Path

# A separate engine instance retains the historical support installer's guards.
path = Path(__file__).with_name('install_support_replies.py')
spec = importlib.util.spec_from_file_location('telegram_menu_install_engine', path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
engine.EXPECTED = '2d6225790c6d177a9f11fe52ecf66b7523a1408e0819752a6fe7a9427d3e40fa'
engine.BASELINES = {'1ede48f63866949e8e65c96082f1797b6fb38e84f266c8a68aa26f7fe50b7e85'}
engine.FEATURE_LABEL = 'Telegram native Menu'
engine.__doc__ = __doc__


def main():
    engine.main()


if __name__ == '__main__':
    main()
