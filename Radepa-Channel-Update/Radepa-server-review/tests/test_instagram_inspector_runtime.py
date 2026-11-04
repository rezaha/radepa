"""Inspector behavior tests; public Instagram is never contacted."""
import asyncio
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

for key, value in {'BOT_TOKEN':'123456:offline-test-token','ADMIN_IDS':'999',
                   'PAYMENT_CARD_NUMBER':'test','PAYMENT_CARD_HOLDER':'test','SERPER_API_KEY':'test'}.items():
    os.environ.setdefault(key,value)
from app.handlers import instagram_inspect as handler
from app.services import instagram_page_inspector as service


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.msg=SimpleNamespace(reply_text=AsyncMock())
        self.update=SimpleNamespace(effective_user=SimpleNamespace(id=999),effective_message=self.msg,
                                    effective_chat=SimpleNamespace(type='private'))
        self.context=SimpleNamespace(args=[])

    async def test_only_admin_private_chat_allowed(self):
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock) as inspect:
            self.update.effective_user.id=123
            await handler.instagram_inspect_command(self.update,self.context)
            self.update.effective_user.id=999;self.update.effective_chat.type='group'
            await handler.instagram_inspect_command(self.update,self.context)
        inspect.assert_not_awaited()

    async def test_arguments_rejected_without_browser(self):
        self.context.args=['account']
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock) as inspect:
            await handler.instagram_inspect_command(self.update,self.context)
        inspect.assert_not_awaited()

    async def test_failure_does_not_leak_exception_and_releases_lock(self):
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock,side_effect=RuntimeError('private detail')):
            await handler.instagram_inspect_command(self.update,self.context)
        self.assertNotIn('private detail',self.msg.reply_text.call_args.args[0])
        self.assertFalse(handler._lock.locked())

    async def test_overlapping_request_does_not_launch_second_browser(self):
        started,release=asyncio.Event(),asyncio.Event()
        async def inspect():
            started.set();await release.wait();return {'status':'ok','http_status':200}
        with patch.object(handler,'inspect_recovery_page',side_effect=inspect) as mocked:
            first=asyncio.create_task(handler.instagram_inspect_command(self.update,self.context))
            await started.wait()
            await handler.instagram_inspect_command(self.update,self.context)
            self.assertIn('در حال اجرا',self.msg.reply_text.call_args.args[0])
            release.set();await first
            self.assertEqual(mocked.call_count,1)

    async def test_cancellation_releases_lock(self):
        async def cancelled():raise asyncio.CancelledError()
        with patch.object(handler,'inspect_recovery_page',side_effect=cancelled):
            with self.assertRaises(asyncio.CancelledError):await handler.instagram_inspect_command(self.update,self.context)
        self.assertFalse(handler._lock.locked())

    async def test_denied_page_is_unavailable_not_zero_results(self):
        result={'status':'http_error','http_status':403,'username_fields':0,'continue_buttons':0}
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock,return_value=result):
            await handler.instagram_inspect_command(self.update,self.context)
        text=self.msg.reply_text.call_args.args[0]
        self.assertIn('HTTP 403',text)
        self.assertIn('علت دقیق',text)
        self.assertIn('ساختار فرم قابل ارزیابی نیست',text)
        self.assertNotIn('تعداد فیلدها: 0',text)
        self.assertNotIn('دکمه ادامه: 0',text)

    async def test_rate_limit_does_not_retry(self):
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock,
                          return_value={'status':'http_error','http_status':429}) as inspect:
            await handler.instagram_inspect_command(self.update,self.context)
        inspect.assert_awaited_once()
        self.assertIn('HTTP 429',self.msg.reply_text.call_args.args[0])

    async def test_no_response_does_not_show_form_counts(self):
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock,return_value={'status':'no_response'}):
            await handler.instagram_inspect_command(self.update,self.context)
        self.assertIn('پاسخ قابل بررسی',self.msg.reply_text.call_args.args[0])
        self.assertNotIn('تعداد فیلدها:',self.msg.reply_text.call_args.args[0])

    async def test_success_still_displays_form_counts(self):
        with patch.object(handler,'inspect_recovery_page',new_callable=AsyncMock,
                          return_value={'status':'ok','http_status':200,'username_fields':1,'continue_buttons':1}):
            await handler.instagram_inspect_command(self.update,self.context)
        self.assertIn('تعداد فیلدها: 1',self.msg.reply_text.call_args.args[0])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def check(self,response=None,error=None):
        page=SimpleNamespace(goto=AsyncMock(return_value=response,side_effect=error),
                              get_by_role=MagicMock(return_value=SimpleNamespace(count=AsyncMock(return_value=1))))
        browser=SimpleNamespace(new_page=AsyncMock(return_value=page),close=AsyncMock())
        factory=MagicMock()
        self.launch=AsyncMock(return_value=browser)
        factory.return_value.__aenter__.return_value=SimpleNamespace(chromium=SimpleNamespace(launch=self.launch))
        with patch('playwright.async_api.async_playwright',factory):
            if error:
                with self.assertRaises(type(error)):await service.inspect_recovery_page()
                result=None
            else:result=await service.inspect_recovery_page()
        browser.close.assert_awaited_once()
        if response is not None and not response.ok:
            page.get_by_role.assert_not_called()
        return result

    async def test_session_proxy_is_used_without_credentials_in_server_url(self):
        with patch.dict(os.environ,{'HTTPS_PROXY':'http://user:synthetic-secret@proxy.example:8080'}):
            await self.check(SimpleNamespace(ok=True,status=200))
        proxy=self.launch.call_args.kwargs['proxy']
        self.assertEqual(proxy['server'],'http://proxy.example:8080')
        self.assertEqual(proxy['username'],'user')
        self.assertEqual(proxy['password'],'synthetic-secret')

    async def test_no_response(self):self.assertEqual(await self.check(),{'status':'no_response'})
    async def test_http_failure(self):
        self.assertEqual(await self.check(SimpleNamespace(ok=False,status=403)),
                         {'status':'http_error','http_status':403})

    async def test_server_error_does_not_report_form_counts(self):
        self.assertEqual(await self.check(SimpleNamespace(ok=False,status=503)),
                         {'status':'http_error','http_status':503})
    async def test_navigation_failure_cleans_browser(self):await self.check(error=RuntimeError('navigation'))
    async def test_success(self):self.assertEqual((await self.check(SimpleNamespace(ok=True,status=200)))['http_status'],200)


class LocalBrowserTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which('chromium'),'System Chromium not available')
    async def test_real_browser_on_local_fixture(self):
        class Page(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(403 if self.path == '/denied' else 200);self.end_headers()
                self.wfile.write(b'<html><input aria-label="Account"><button>Continue</button></html>')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Page)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(service,'RECOVERY_URL',f'http://127.0.0.1:{server.server_port}/'),patch.dict(os.environ,{'INSTAGRAM_INSPECT_BROWSER_PATH':shutil.which('chromium'),'HTTPS_PROXY':'','https_proxy':'','HTTP_PROXY':'','http_proxy':''}):
                result=await service.inspect_recovery_page()
            self.assertEqual(result,{'status':'ok','http_status':200,'username_fields':1,'continue_buttons':1})
            with patch.object(service,'RECOVERY_URL',f'http://127.0.0.1:{server.server_port}/denied'),patch.dict(os.environ,{'INSTAGRAM_INSPECT_BROWSER_PATH':shutil.which('chromium'),'HTTPS_PROXY':'','https_proxy':'','HTTP_PROXY':'','http_proxy':''}):
                denied=await service.inspect_recovery_page()
            self.assertEqual(denied,{'status':'http_error','http_status':403})
        finally:
            server.shutdown();server.server_close();thread.join()

class StartupIsolationTests(unittest.TestCase):
    def test_bot_starts_without_playwright_and_registers_nonblocking_command(self):
        import subprocess,sys,textwrap
        code=textwrap.dedent('''
            import builtins,os,tempfile
            from dataclasses import replace
            from unittest.mock import patch
            os.environ.update({'BOT_TOKEN':'123456:offline-test-token','ADMIN_IDS':'999',
                'PAYMENT_CARD_NUMBER':'test','PAYMENT_CARD_HOLDER':'test','SERPER_API_KEY':'test'})
            real_import=builtins.__import__
            def guarded(name,*args,**kwargs):
                if name.startswith('playwright'):
                    raise ImportError('Optional browser support absent')
                return real_import(name,*args,**kwargs)
            with patch('builtins.__import__',side_effect=guarded):
                from app import main
                with tempfile.TemporaryDirectory() as tmp:
                    cfg=replace(main.config,db_path=tmp+'/bot.db',log_file=tmp+'/bot.log')
                    with patch.object(main,'config',cfg),patch.object(main.Application,'run_polling',autospec=True) as polling:
                        main.main()
                        application=polling.call_args.args[0]
                        handlers=[h for group in application.handlers.values() for h in group]
                        command=next(h for h in handlers if 'instagram' in getattr(h,'commands',()))
                        assert command.block is False
        ''')
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
