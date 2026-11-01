"""Offline staging health check: synthetic config, no Telegram polling or Instagram."""
import argparse
import asyncio
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(work, browser=False, tests=False):
    work.mkdir(parents=True, exist_ok=True)
    fake = {'BOT_TOKEN': '123456:offline-test-token', 'ADMIN_IDS': '999',
            'PAYMENT_CARD_NUMBER': 'test', 'PAYMENT_CARD_HOLDER': 'test',
            'SERPER_API_KEY': 'offline-test-key', 'ABSTRACT_API_KEY': '',
            'SERPAPI_KEY': '', 'SERPAPI_KEY_2': '', 'GOOGLE_API_KEY': '', 'GOOGLE_CSE_ID': '',
            'DB_PATH': str(work / 'bot.db'), 'LOG_FILE': str(work / 'bot.log'), 'TELEGRAM_PROXY_URL': ''}
    os.environ.update(fake)
    summary = {}
    # Prove ordinary bot startup is independent of the optional browser package.
    import builtins
    original_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.startswith('playwright'):
            raise ImportError('Browser intentionally unavailable during startup check')
        return original_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=guarded):
        from app import main
        cfg = replace(main.config, db_path=str(work / 'bot.db'), log_file=str(work / 'bot.log'))
        with patch.object(main, 'config', cfg), patch.object(main.Application, 'run_polling', autospec=True) as polling:
            main.main()
            polling.assert_called_once()
            app = polling.call_args.args[0]
            handlers = [h for group in app.handlers.values() for h in group]
            command = next(h for h in handlers if 'instagram' in getattr(h, 'commands', ()))
            assert command.block is False
    summary['startup_without_playwright'] = 'passed'
    if tests:
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        summary['tests'] = {'run': result.testsRun, 'failures': len(result.failures),
                            'errors': len(result.errors), 'skipped': len(result.skipped)}
        if result.testsRun == 0 or not result.wasSuccessful():
            raise RuntimeError('Regression suite did not pass')
    if browser:
        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(b'<html><input aria-label="Account"><button>Continue</button></html>')
            def log_message(self, *args): pass
        from app.services import instagram_page_inspector as inspector
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            # Only this local fixture bypasses the proxy; no external request is made.
            with patch.object(inspector, 'RECOVERY_URL', f'http://127.0.0.1:{server.server_port}/'), patch.dict(os.environ, {
                'HTTPS_PROXY': '', 'https_proxy': '', 'HTTP_PROXY': '', 'http_proxy': ''}):
                observed = asyncio.run(inspector.inspect_recovery_page())
            assert observed == {'status': 'ok', 'http_status': 200, 'username_fields': 1, 'continue_buttons': 1}
            summary['chromium_local_fixture'] = 'passed'
        finally:
            server.shutdown(); server.server_close(); thread.join()
    (work / 'health.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--tests', action='store_true')
    args = parser.parse_args()
    check(args.work.resolve(), args.browser, args.tests)
