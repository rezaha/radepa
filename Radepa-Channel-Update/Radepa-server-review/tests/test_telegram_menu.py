"""Native Menu setup with PTB 21.5 objects and mocked Bot API, never real Telegram."""
import asyncio
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ.update({'BOT_TOKEN':'123456:offline-test-token','ADMIN_IDS':'999',
                   'PAYMENT_CARD_NUMBER':'test','PAYMENT_CARD_HOLDER':'test','SERPER_API_KEY':'test'})
from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeChat, MenuButtonCommands
from telegram.error import Forbidden, TimedOut
from app.services import telegram_menu as menu
from app.db.database import init_db, get_connection
from app.db.repos import UserRepo
from app.handlers.start import start_handler


class MenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot=SimpleNamespace(set_my_commands=AsyncMock(return_value=True),
                                 set_chat_menu_button=AsyncMock(return_value=True))
        self.app=SimpleNamespace(bot=self.bot,bot_data={})

    async def test_startup_sets_private_public_menu_and_admin_override(self):
        with patch.object(menu,'config',SimpleNamespace(admin_ids=[999])):
            await menu.configure_application_menu(self.app)
        public=[];admin=[]
        for call in self.bot.set_my_commands.call_args_list:
            scope=call.kwargs['scope']
            if isinstance(scope,BotCommandScopeAllPrivateChats):public.append(call)
            else:
                self.assertIsInstance(scope,BotCommandScopeChat)
                self.assertEqual(scope.chat_id,999)
                admin.append(call)
        self.assertEqual({c.kwargs['language_code'] for c in public},{'','fa'})
        self.assertEqual({c.kwargs['language_code'] for c in admin},{'','fa'})
        self.assertTrue(all('admin' not in {v.command for v in c.args[0]} for c in public))
        self.assertTrue(all({'start','admin','reply'} <= {v.command for v in c.args[0]} for c in admin))
        default=self.bot.set_chat_menu_button.call_args_list[0]
        self.assertNotIn('chat_id',default.kwargs)
        self.assertIsInstance(default.kwargs['menu_button'],MenuButtonCommands)
        self.assertEqual(self.bot.set_chat_menu_button.call_args_list[1].kwargs['chat_id'],999)

    async def test_all_commands_are_valid_and_unique(self):
        for commands in (menu.PUBLIC_COMMANDS,menu.ADMIN_COMMANDS):
            self.assertEqual(len(commands),len({c.command for c in commands}))
            self.assertLessEqual(len(commands),100)
            for command in commands:
                self.assertRegex(command.command,r'^[a-z0-9_]{1,32}$')
                self.assertTrue(1 <= len(command.description) <= 256)

    async def test_cache_avoids_repeated_calls_but_role_changes_refresh(self):
        self.assertTrue(await menu.ensure_private_menu(self.bot,self.app.bot_data,999,True))
        self.assertTrue(await menu.ensure_private_menu(self.bot,self.app.bot_data,999,True))
        self.assertEqual(self.bot.set_my_commands.await_count,2)
        self.assertTrue(await menu.ensure_private_menu(self.bot,self.app.bot_data,999,False))
        self.assertEqual(self.bot.set_my_commands.await_count,4)
        self.assertNotIn('admin',{c.command for c in self.bot.set_my_commands.call_args.args[0]})

    async def test_unknown_admin_chat_does_not_block_other_admins(self):
        async def commands(*args,**kwargs):
            scope=kwargs['scope']
            if isinstance(scope,BotCommandScopeChat) and scope.chat_id==999:raise Forbidden('private-secret')
            return True
        self.bot.set_my_commands.side_effect=commands
        with patch.object(menu,'config',SimpleNamespace(admin_ids=[999,1000,1000])):
            await menu.configure_application_menu(self.app)
        self.assertNotIn(999,self.app.bot_data['telegram_menu_chats'])
        self.assertTrue(self.app.bot_data['telegram_menu_chats'][1000])
        calls=[c for c in self.bot.set_my_commands.call_args_list
               if isinstance(c.kwargs['scope'],BotCommandScopeChat) and c.kwargs['scope'].chat_id==1000]
        self.assertEqual(len(calls),2)

    async def test_api_failure_is_not_cached_and_can_retry(self):
        self.bot.set_my_commands.side_effect=TimedOut()
        self.assertFalse(await menu.ensure_private_menu(self.bot,self.app.bot_data,123,False))
        self.assertNotIn(123,self.app.bot_data['telegram_menu_chats'])
        self.bot.set_my_commands.side_effect=None
        self.assertTrue(await menu.ensure_private_menu(self.bot,self.app.bot_data,123,False))

    async def test_unconfirmed_button_is_not_cached(self):
        self.bot.set_chat_menu_button.return_value=False
        self.assertFalse(await menu.ensure_private_menu(self.bot,self.app.bot_data,123,False))
        self.assertNotIn(123,self.app.bot_data['telegram_menu_chats'])

    async def test_chat_timeout_is_nonfatal(self):
        with patch.object(menu,'_chat_menu',new=AsyncMock(side_effect=asyncio.TimeoutError())):
            self.assertFalse(await menu.ensure_private_menu(self.bot,self.app.bot_data,123,False))

    async def test_startup_timeout_is_nonfatal(self):
        with patch.object(menu,'_configure',new=AsyncMock(side_effect=asyncio.TimeoutError())):
            await menu.configure_application_menu(self.app)

    async def test_global_failure_still_attempts_admin_menu(self):
        async def commands(*args,**kwargs):
            if isinstance(kwargs['scope'],BotCommandScopeAllPrivateChats):raise TimedOut()
            return True
        self.bot.set_my_commands.side_effect=commands
        with patch.object(menu,'config',SimpleNamespace(admin_ids=[999])):
            await menu.configure_application_menu(self.app)
        self.assertTrue(self.app.bot_data['telegram_menu_chats'][999])

    async def test_start_shows_keyboard_even_when_menu_api_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            init_db(str(Path(folder)/'menu.db'))
            UserRepo.upsert(123,None,'User')
            with get_connection() as conn:conn.execute('UPDATE users SET email_credits=5,instagram_credits=6')
            msg=SimpleNamespace(reply_text=AsyncMock())
            update=SimpleNamespace(effective_user=SimpleNamespace(id=123,username=None,first_name='User'),
                effective_chat=SimpleNamespace(type='private'),effective_message=msg,message=msg)
            ctx=SimpleNamespace(bot=self.bot,bot_data={},user_data={'awaiting_breach_email':True})
            self.bot.set_my_commands.side_effect=Forbidden('not logged')
            await start_handler(update,ctx)
            msg.reply_text.assert_awaited_once()
            self.assertTrue(msg.reply_text.call_args.kwargs['reply_markup'].is_persistent)
            account=UserRepo.get_by_telegram_id(123)
            self.assertEqual((account['email_credits'],account['instagram_credits']),(5,6))
            self.assertNotIn('awaiting_breach_email',ctx.user_data)
