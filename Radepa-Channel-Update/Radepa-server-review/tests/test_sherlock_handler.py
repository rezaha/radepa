"""Sherlock command and routing regressions, entirely offline."""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ.update({'BOT_TOKEN':'123456:offline-test-token','ADMIN_IDS':'999',
                   'PAYMENT_CARD_NUMBER':'test','PAYMENT_CARD_HOLDER':'test','SERPER_API_KEY':'test'})
from telegram import Update, User
from telegram.error import Forbidden
from telegram.ext import ExtBot
from app.db.database import init_db, get_connection
from app.db.repos import UserRepo, OrderRepo
from app.handlers import sherlock
from app.services.sherlock_service import SherlockService, SherlockResult, SiteResult


class SherlockHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'bot.db'
        init_db(str(self.path))
        UserRepo.upsert(123,None,'User')
        with get_connection() as conn:conn.execute('UPDATE users SET email_credits=5,instagram_credits=6,credits=7')
        self.message=SimpleNamespace(text='/sherlock @Example_User',reply_text=AsyncMock())
        self.update=SimpleNamespace(effective_user=SimpleNamespace(id=123),effective_message=self.message,
            effective_chat=SimpleNamespace(id=123,type='private'),callback_query=None)
        self.service=SherlockService(enabled=True)
        self.tasks=[]
        def create(work,**kwargs):
            task=asyncio.create_task(work);self.tasks.append(task);return task
        self.ctx=SimpleNamespace(args=['@Example_User'],bot_data={'sherlock_service':self.service},
            user_data={},application=SimpleNamespace(create_task=create))

    async def asyncTearDown(self):
        await self.service.close()
        self.temp.cleanup()

    async def test_background_ack_free_and_no_implicit_input_state(self):
        begun,release=asyncio.Event(),asyncio.Event()
        async def execute(permit):
            begun.set();await release.wait()
            return SherlockResult('complete',(SiteResult('Example','https://example.com/u','Claimed'),))
        with patch.object(self.service,'execute',side_effect=execute):
            await sherlock.sherlock_command(self.update,self.ctx)
            await asyncio.wait_for(begun.wait(),1)
            self.assertIn('در حال جستجو',self.message.reply_text.call_args.args[0])
            self.assertEqual(self.ctx.user_data,{})
            release.set();await asyncio.gather(*self.tasks)
        account=UserRepo.get_by_telegram_id(123)
        self.assertEqual((account['email_credits'],account['instagram_credits'],account['credits']),(5,6,7))
        text='\n'.join(c.args[0] for c in self.message.reply_text.call_args_list)
        self.assertIn('https://example.com/u',text)
        self.assertIn('مالکیت مشترک',text)
        self.assertEqual(self.service._active,{})

    async def test_invalid_username_never_schedules(self):
        for args in ([],['one','two'],['@@user'],['--csv'],['user@example.com']):
            self.ctx.args=args
            await sherlock.sherlock_command(self.update,self.ctx)
        self.assertEqual(self.tasks,[])
        self.assertEqual(self.service._active,{})

    async def test_group_blocked_and_unregistered_cannot_search(self):
        self.update.effective_chat.type='group'
        await sherlock.sherlock_command(self.update,self.ctx)
        self.update.effective_chat.type='private'
        UserRepo.set_blocked(123,True)
        await sherlock.sherlock_command(self.update,self.ctx)
        self.update.effective_user.id=456
        await sherlock.sherlock_command(self.update,self.ctx)
        self.assertEqual(self.tasks,[])

    async def test_disabled_and_busy_are_not_started(self):
        self.service.enabled=False
        await sherlock.sherlock_command(self.update,self.ctx)
        self.service.enabled=True
        permit=self.service.reserve(123,'first')
        await sherlock.sherlock_command(self.update,self.ctx)
        self.service.finish(permit)
        await sherlock.sherlock_command(self.update,self.ctx)
        self.assertEqual(self.tasks,[])

    async def test_prompt_never_enters_a_username_mode(self):
        await sherlock.sherlock_prompt(self.update,self.ctx)
        self.assertEqual(self.ctx.user_data,{})
        self.assertEqual(self.tasks,[])
        self.assertIn('/sherlock YOUR_USERNAME',self.message.reply_text.call_args.args[0])

    async def test_ack_failure_does_not_leak_a_permit(self):
        self.message.reply_text.side_effect=Forbidden('private message')
        await sherlock.sherlock_command(self.update,self.ctx)
        self.assertEqual(self.service._active,{})
        self.assertEqual(self.tasks,[])

    async def test_cancellation_before_scheduling_releases_permit(self):
        self.message.reply_text.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await sherlock.sherlock_command(self.update,self.ctx)
        self.assertEqual(self.service._active,{})

    async def test_render_complete_zero_differs_from_failure_and_timeout(self):
        zero=sherlock.format_report('example',SherlockResult('complete',(SiteResult('One','https://example.com/u','Available'),)))
        self.assertIn('جستجو کامل شد و نتیجه‌ای پیدا نشد',zero[0])
        for status in ('partial','timeout','failed','unavailable'):
            text='\n'.join(sherlock.format_report('example',SherlockResult(status)))
            self.assertNotIn('جستجو کامل شد',text)
            self.assertIn('بررسی کامل نشده',text)

    async def test_report_limits_links_and_utf16_message_length(self):
        rows=tuple(SiteResult('😀'*80,f'https://example.com/{i}/'+'a'*900,'Claimed') for i in range(60))
        pages=sherlock.format_report('example',SherlockResult('partial',rows))
        self.assertIn('فقط 50 لینک',pages[0])
        for page in pages:
            self.assertLessEqual(len(page.encode('utf-16-le'))//2,4096)
            self.assertLessEqual(page.count('https://'),5)
        self.assertEqual(sum(page.count('https://') for page in pages),50)

    async def test_deleted_or_newly_blocked_user_gets_no_results(self):
        async def execute(permit):
            UserRepo.set_blocked(123,True)
            return SherlockResult('complete')
        with patch.object(self.service,'execute',side_effect=execute):
            await sherlock.sherlock_command(self.update,self.ctx)
            await asyncio.gather(*self.tasks)
        self.assertEqual(self.message.reply_text.await_count,1)

    async def test_unexpected_execution_failure_is_reported_and_releases_capacity(self):
        with patch.object(self.service,'execute',side_effect=OSError('temporary storage unavailable')):
            await sherlock.sherlock_command(self.update,self.ctx)
            await asyncio.gather(*self.tasks)
        text='\n'.join(c.args[0] for c in self.message.reply_text.call_args_list)
        self.assertIn('جستجو کامل نشد',text)
        self.assertNotIn('جستجو کامل شد',text)
        self.assertEqual(self.service._active,{})

    async def test_real_application_command_is_nonblocking_and_other_routes_survive(self):
        from app import main
        cfg=replace(main.config,db_path=str(self.path),log_file=str(Path(self.temp.name)/'log'),sherlock_enabled=True)
        with patch.object(main,'config',cfg),patch.object(main.Application,'run_polling',autospec=True) as polling:
            main.main()
        app=polling.call_args.args[0]
        service=app.bot_data['sherlock_service']
        released,started=asyncio.Event(),asyncio.Event()
        async def execute(permit):
            started.set();await released.wait();return SherlockResult('complete')
        def update(text,number,command=False,user_id=123):
            message={'message_id':number,'date':1,'chat':{'id':user_id,'type':'private'},
                     'from':{'id':user_id,'is_bot':False,'first_name':'User'},'text':text}
            if command:message['entities']=[{'type':'bot_command','offset':0,'length':9}]
            return Update.de_json({'update_id':number,'message':message},app.bot)
        app.bot._bot_user=User(777,'Bot',True,username='test_bot')
        try:
            with patch.object(ExtBot,'initialize',new=AsyncMock()),patch.object(ExtBot,'send_message',new=AsyncMock(return_value=SimpleNamespace(message_id=100))),patch.object(service,'execute',side_effect=execute) as search:
                await app.initialize();app._running=True
                await asyncio.wait_for(app.process_update(update('/sherlock Example_User',1,True)),1)
                await asyncio.wait_for(started.wait(),1)
                app.user_data[123]['awaiting_support_message']=True
                await app.process_update(update('a normal support message',2))
                self.assertNotIn('awaiting_support_message',app.user_data[123])
                app.user_data[123]['awaiting_instagram_username']=True
                with patch.object(main,'receive_username_handler',new_callable=AsyncMock) as instagram:
                    await app.process_update(update('ordinary_username',3))
                    instagram.assert_awaited_once()
                app.user_data[123].clear()
                main._seed_plans()
                from app.services.products import EMAIL_PLAN
                OrderRepo.create(123,EMAIL_PLAN,199000)
                with patch.object(main,'receive_evidence_handler',new_callable=AsyncMock) as payment:
                    await app.process_update(update('a payment receipt reference',4))
                    payment.assert_awaited_once()
                app.user_data[123]['awaiting_breach_email']=True
                with patch('app.handlers.breach._lookup',new_callable=AsyncMock,return_value=True) as email:
                    await app.process_update(update('test@example.com',5))
                    email.assert_awaited_once()
                UserRepo.upsert(999,None,'Admin')
                with patch.object(main,'admin_text_handler',new_callable=AsyncMock,return_value=True) as admin:
                    await app.process_update(update('an admin panel input',6,user_id=999))
                    admin.assert_awaited_once()
                from app.utils.keyboards import SHERLOCK_BUTTON
                app.user_data[123]['awaiting_breach_email']=True
                await app.process_update(update(SHERLOCK_BUTTON,7))
                self.assertNotIn('awaiting_breach_email',app.user_data[123])
                self.assertEqual(search.await_count,1)
                released.set()
                await asyncio.gather(*tuple(service._tasks))
                self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'],5)
                app._running=False
                await main._on_shutdown(app)
                await app.shutdown()
        finally:
            app._running=False
            released.set()
            await service.close()
            for request in app.bot._request:await request.shutdown()
            loop=asyncio.get_event_loop_policy().get_event_loop()
            if not loop.is_running():loop.close()
