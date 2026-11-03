"""Temporary SQLite and mocked Telegram only; no messages to real users."""
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

from telegram import Update
from telegram.error import Forbidden, BadRequest, TimedOut
from telegram.ext import ApplicationHandlerStop, ExtBot
from app.db.database import init_db, get_connection
from app.db.repos import UserRepo
from app.db.support_repo import SupportRepo
from app.handlers import support

USER_ID = 7000000123


class SupportReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'bot.db'
        init_db(str(self.db))
        UserRepo.upsert(USER_ID,None,'User [*_]')
        self.msg=SimpleNamespace(text='سلام [*_] <text>',message_id=10,
                                 reply_to_message=None,reply_text=AsyncMock())
        self.chat=SimpleNamespace(id=USER_ID,type='private')
        self.user=SimpleNamespace(id=USER_ID,username=None,first_name='User [*_]')
        self.query=SimpleNamespace(data='',answer=AsyncMock(),edit_message_text=AsyncMock())
        self.update=SimpleNamespace(effective_user=self.user,effective_chat=self.chat,
                                    effective_message=self.msg,message=self.msg,callback_query=self.query)
        self.bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=51)),
                                 copy_message=AsyncMock(),get_chat=AsyncMock())
        self.context=SimpleNamespace(bot=self.bot,user_data={'awaiting_support_message':True})
        self.config_patch=patch.object(support,'config',SimpleNamespace(admin_ids=[999]))
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.temp.cleanup()

    def become_admin(self):
        self.user.id=999;self.chat.id=999
        self.context.user_data={}

    def ticket(self,notification_id=51,admin_id=999):
        ticket=SupportRepo.create(USER_ID,10)
        SupportRepo.record_delivery(admin_id,notification_id,ticket)
        return ticket

    async def test_no_username_and_markup_are_delivered_literally(self):
        await support.receive_support_message(self.update,self.context)
        sent=self.bot.send_message.call_args.kwargs
        self.assertIsNone(sent['parse_mode'])
        self.assertIn('ندارد',sent['text'])
        self.assertIn('سلام [*_] <text>',sent['text'])
        self.assertEqual(SupportRepo.for_reply(999,51)['telegram_user_id'],USER_ID)
        self.assertNotIn('awaiting_support_message',self.context.user_data)
        data=sent['reply_markup'].inline_keyboard[0][0].callback_data
        self.assertTrue(data.startswith('support:reply:'))

    async def test_no_success_claim_when_all_admins_unreachable(self):
        self.bot.send_message.side_effect=Forbidden('private exception')
        await support.receive_support_message(self.update,self.context)
        self.assertIn('انجام نشد',self.msg.reply_text.call_args.args[0])
        self.assertNotIn('private exception',self.msg.reply_text.call_args.args[0])
        self.assertTrue(self.context.user_data['awaiting_support_message'])

    async def test_long_messages_are_split_and_each_part_is_replyable(self):
        self.msg.text='😀'*2048
        self.bot.send_message.side_effect=[SimpleNamespace(message_id=51),SimpleNamespace(message_id=52)]
        await support.receive_support_message(self.update,self.context)
        for sent in self.bot.send_message.call_args_list:
            self.assertLessEqual(len(sent.kwargs['text'].encode('utf-16-le'))//2,4096)
        self.assertEqual(SupportRepo.for_reply(999,52)['telegram_user_id'],USER_ID)

    async def test_partial_delivery_does_not_claim_complete_delivery(self):
        self.msg.text='x'*2000
        self.bot.send_message.side_effect=[SimpleNamespace(message_id=51),TimedOut()]
        await support.receive_support_message(self.update,self.context)
        self.assertIn('انجام نشد',self.msg.reply_text.call_args.args[0])
        self.assertTrue(self.context.user_data['awaiting_support_message'])

    async def test_one_unreachable_admin_does_not_block_another(self):
        with patch.object(support,'config',SimpleNamespace(admin_ids=[999,1000])):
            self.bot.send_message.side_effect=[Forbidden('blocked'),SimpleNamespace(message_id=51)]
            await support.receive_support_message(self.update,self.context)
        self.assertEqual(SupportRepo.for_reply(1000,51)['telegram_user_id'],USER_ID)
        self.assertNotIn('awaiting_support_message',self.context.user_data)

    async def test_direct_reply_uses_persisted_id_after_context_reset(self):
        self.ticket();init_db(str(self.db));self.become_admin()
        self.msg.message_id=80;self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.assertTrue(await support.receive_admin_reply(self.update,self.context))
        self.bot.copy_message.assert_awaited_once_with(chat_id=USER_ID,from_chat_id=999,message_id=80)

    async def test_button_creates_persisted_force_reply_prompt(self):
        ticket=self.ticket();self.become_admin()
        self.query.data='support:reply:'+ticket
        self.bot.send_message.return_value=SimpleNamespace(message_id=61)
        await support.support_reply_callback(self.update,self.context)
        self.assertTrue(self.bot.send_message.call_args.kwargs['reply_markup'].force_reply)
        self.assertEqual(SupportRepo.for_reply(999,61)['telegram_user_id'],USER_ID)
        self.context.user_data.clear();self.msg.reply_to_message=SimpleNamespace(message_id=61)
        self.assertTrue(await support.receive_admin_reply(self.update,self.context))

    async def test_non_admin_cannot_reply_or_use_button_or_command(self):
        self.ticket();self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.assertFalse(await support.receive_admin_reply(self.update,self.context))
        await support.support_reply_callback(self.update,self.context)
        self.msg.text=f'/reply {USER_ID} hello'
        await support.support_reply_command(self.update,self.context)
        self.bot.copy_message.assert_not_awaited();self.bot.send_message.assert_not_awaited()

    async def test_admin_in_group_cannot_send_reply(self):
        self.ticket();self.become_admin();self.chat.type='group'
        self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.assertFalse(await support.receive_admin_reply(self.update,self.context))
        self.msg.text=f'/reply {USER_ID} hello'
        await support.support_reply_command(self.update,self.context)
        self.bot.copy_message.assert_not_awaited();self.bot.send_message.assert_not_awaited()

    async def test_delivery_ids_are_scoped_to_admin_chat(self):
        self.ticket(admin_id=1000);self.become_admin()
        self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.assertFalse(await support.receive_admin_reply(self.update,self.context))
        self.bot.copy_message.assert_not_awaited()

    async def test_unknown_quote_is_not_parsed_for_recipient(self):
        self.become_admin()
        self.msg.reply_to_message=SimpleNamespace(message_id=9999,text=f'🆔 شناسه: {USER_ID}')
        self.assertFalse(await support.receive_admin_reply(self.update,self.context))
        self.bot.copy_message.assert_not_awaited()

    async def test_legacy_bot_notification_explains_command_instead_of_guessing_id(self):
        self.become_admin();self.bot.id=777
        self.msg.reply_to_message=SimpleNamespace(message_id=9999,from_user=SimpleNamespace(id=777),
            text=f'📩 پیام پشتیبانی جدید\n🆔 شناسه: {USER_ID}')
        self.assertTrue(await support.receive_admin_reply(self.update,self.context))
        self.bot.copy_message.assert_not_awaited();self.bot.send_message.assert_not_awaited()
        self.assertIn('/reply USER_ID',self.msg.reply_text.call_args.args[0])

    async def test_copy_failure_is_reported_without_success_or_sensitive_exception(self):
        self.ticket();self.become_admin();self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.bot.copy_message.side_effect=Forbidden('sensitive detail')
        self.assertTrue(await support.receive_admin_reply(self.update,self.context))
        text=self.msg.reply_text.call_args.args[0]
        self.assertIn('ارسال نشد',text);self.assertNotIn('✅',text);self.assertNotIn('sensitive detail',text)

    async def test_timeout_is_not_reported_as_success(self):
        self.ticket();self.become_admin();self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.bot.copy_message.side_effect=TimedOut()
        self.assertTrue(await support.receive_admin_reply(self.update,self.context))
        self.assertIn('تأیید نشد',self.msg.reply_text.call_args.args[0])

    async def test_numeric_command_preserves_body_and_cannot_change_balances(self):
        self.become_admin();self.msg.text=f'/reply {USER_ID} سلام\nمتن [*_]'
        before=UserRepo.get_by_telegram_id(USER_ID)
        await support.support_reply_command(self.update,self.context)
        self.bot.send_message.assert_awaited_once_with(chat_id=USER_ID,text='سلام\nمتن [*_]',parse_mode=None)
        self.assertEqual(UserRepo.get_by_telegram_id(USER_ID),before)

    async def test_username_resolves_known_id_and_checks_current_username(self):
        UserRepo.upsert(USER_ID,'Known_User','User')
        self.become_admin();self.msg.text='/reply @known_user سلام'
        self.bot.get_chat.return_value=SimpleNamespace(username='Known_User')
        await support.support_reply_command(self.update,self.context)
        self.bot.get_chat.assert_awaited_once_with(USER_ID)
        self.bot.send_message.assert_awaited_once_with(chat_id=USER_ID,text='سلام',parse_mode=None)

    async def test_stale_username_is_not_used(self):
        UserRepo.upsert(USER_ID,'old_name','User')
        self.become_admin();self.msg.text='/reply @old_name سلام'
        self.bot.get_chat.return_value=SimpleNamespace(username='new_name')
        await support.support_reply_command(self.update,self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_ambiguous_or_unknown_username_is_not_used(self):
        UserRepo.upsert(USER_ID,'duplicate','User');UserRepo.upsert(456,'DUPLICATE','Other')
        self.become_admin()
        for target in ('@duplicate','@unknown','999999999','-1000','999999999999999999999999999'):
            self.msg.text=f'/reply {target} hello'
            await support.support_reply_command(self.update,self.context)
        self.bot.send_message.assert_not_awaited();self.bot.get_chat.assert_not_awaited()

    async def test_username_api_failure_does_not_guess_recipient(self):
        UserRepo.upsert(USER_ID,'known','User');self.become_admin()
        self.msg.text='/reply @known hello';self.bot.get_chat.side_effect=BadRequest('not found')
        await support.support_reply_command(self.update,self.context)
        self.bot.send_message.assert_not_awaited()

    async def test_reply_command_delivery_failure(self):
        self.become_admin();self.msg.text=f'/reply {USER_ID} hello'
        self.bot.send_message.side_effect=Forbidden('blocked')
        await support.support_reply_command(self.update,self.context)
        self.assertIn('ارسال نشد',self.msg.reply_text.call_args.args[0])

    async def test_router_stops_email_admin_and_payment_routes(self):
        self.ticket();self.become_admin();self.msg.reply_to_message=SimpleNamespace(message_id=51)
        self.msg.text='person@example.com'
        self.context.user_data={'awaiting_breach_email':True,'adm_await':'broadcast','rejecting_order_id':'order'}
        with self.assertRaises(ApplicationHandlerStop):
            await support.support_reply_router(self.update,self.context)
        self.assertEqual(self.context.user_data['adm_await'],'broadcast')
        self.assertTrue(self.context.user_data['awaiting_breach_email'])

    async def test_migration_is_additive_and_user_deletion_cascades(self):
        ticket=self.ticket()
        with get_connection() as conn:
            conn.execute('UPDATE users SET email_credits=7,instagram_credits=8 WHERE telegram_user_id=?',(USER_ID,))
        init_db(str(self.db));init_db(str(self.db))
        user=UserRepo.get_by_telegram_id(USER_ID)
        self.assertEqual((user['email_credits'],user['instagram_credits']),(7,8))
        self.assertIsNotNone(SupportRepo.get(ticket))
        with get_connection() as conn:conn.execute('DELETE FROM users WHERE telegram_user_id=?',(USER_ID,))
        self.assertIsNone(SupportRepo.for_reply(999,51))

    async def test_application_routes_registered_support_reply_before_email(self):
        from app import main
        cfg=replace(main.config,db_path=str(self.db),log_file=str(Path(self.temp.name)/'log'))
        with patch.object(main,'config',cfg),patch.object(main.Application,'run_polling',autospec=True) as polling:
            main.main()
        application=polling.call_args.args[0]
        try:
            handler=application.handlers[-3][0]
            self.assertIs(handler.callback,support.support_reply_router)
            self.assertIn(-1,application.handlers)
            user_reply={'update_id':1,'message':{'message_id':80,'date':1,
                'chat':{'id':999,'type':'private'},'from':{'id':999,'is_bot':False,'first_name':'Admin'},
                'text':'person@example.com','reply_to_message':{'message_id':51,'date':1,'chat':{'id':999,'type':'private'},'text':'notification'}}}
            update=Update.de_json(user_reply,application.bot)
            self.assertTrue(handler.check_update(update))
            self.ticket()
            with patch.object(ExtBot,'initialize',new=AsyncMock()),patch.object(ExtBot,'copy_message',new=AsyncMock()) as copy,patch.object(ExtBot,'send_message',new=AsyncMock()):
                await application.initialize()
                application.user_data[999].update({'awaiting_breach_email':True,'adm_await':'broadcast'})
                await application.process_update(update)
                copy.assert_awaited_once_with(chat_id=USER_ID,from_chat_id=999,message_id=80)
                self.assertEqual(application.user_data[999]['adm_await'],'broadcast')
                self.assertTrue(application.user_data[999]['awaiting_breach_email'])
                user_reply['update_id']=2
                user_reply['message'].pop('text')
                user_reply['message']['message_id']=81
                user_reply['message']['photo']=[{'file_id':'synthetic','file_unique_id':'synthetic','width':10,'height':10}]
                await application.process_update(Update.de_json(user_reply,application.bot))
                self.assertEqual(copy.await_count,2)
                self.assertEqual(copy.await_args.kwargs,{'chat_id':USER_ID,'from_chat_id':999,'message_id':81})
                await application.shutdown()
            commands=[h.commands for h in application.handlers[0] if hasattr(h,'commands')]
            self.assertTrue(any('reply' in names and 'supportreply' in names for names in commands))
        finally:
            for request in application.bot._request:
                await request.shutdown()
            loop=asyncio.get_event_loop_policy().get_event_loop()
            if not loop.is_running():loop.close()
