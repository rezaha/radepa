"""Offline tests: synthetic identifiers, temporary SQLite, mocked external services."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.update({
    "BOT_TOKEN": "123456:offline-test-token", "ADMIN_IDS": "999",
    "PAYMENT_CARD_NUMBER": "test", "PAYMENT_CARD_HOLDER": "test",
    "SERPER_API_KEY": "offline-test-key",
})

import httpx
from telegram.ext import ApplicationHandlerStop
from app.db.database import init_db
from app.db.repos import UserRepo
from app.handlers import breach as b
from app.handlers.email_verify import verifyemail_command
from app.handlers.start import _inline_main_menu, _persistent_keyboard
from app.services.leakcheck_public import BreachSummary, LeakCheckPublic, LeakCheckUnavailable


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        init_db(str(Path(self.temp.name) / "test.db"))
        UserRepo.upsert(123, "test", "test")
        from app.db.database import get_connection
        with get_connection() as conn:
            conn.execute("UPDATE users SET email_credits=5 WHERE telegram_user_id=123")
        self.msg = SimpleNamespace(reply_document=AsyncMock(), chat=SimpleNamespace(type="private"),
                                   text="person@example.com", reply_text=AsyncMock())
        self.update = SimpleNamespace(effective_message=self.msg,
                                      effective_user=SimpleNamespace(id=123), callback_query=None)
        self.api = SimpleNamespace(lookup_email=AsyncMock(return_value=BreachSummary(
            2, ("email", "password"), (("Example <Source>", "2020-01"),))))
        self.ctx = SimpleNamespace(args=["person@example.com"], user_data={},
                                   bot_data={"leakcheck_public": self.api})

    def tearDown(self):
        self.temp.cleanup()

    async def test_command_needs_no_ownership_table_or_smtp(self):
        with patch("smtplib.SMTP", side_effect=AssertionError("SMTP called")), \
             patch("smtplib.SMTP_SSL", side_effect=AssertionError("SMTP called")):
            await b.breach_command(self.update, self.ctx)
        self.api.lookup_email.assert_awaited_once_with("person@example.com")
        result = self.msg.reply_text.call_args.args[0]
        self.assertIn("Example &lt;Source&gt;", result)
        self.assertNotIn("person@example.com", result)
        self.assertIn("Powered by LeakCheck", result)

    async def test_legacy_command_prompts_without_sending_mail(self):
        self.ctx.args = []
        self.ctx.user_data["awaiting_support_message"] = True
        await verifyemail_command(self.update, self.ctx)
        self.assertTrue(self.ctx.user_data["awaiting_breach_email"])
        self.assertNotIn("awaiting_support_message", self.ctx.user_data)
        self.assertIn("نیازی به لینک تأیید نیست", self.msg.reply_text.call_args.args[0])
        self.api.lookup_email.assert_not_called()

    async def test_invalid_and_multiple_emails_do_not_query(self):
        for args in (["invalid"], ["a@example.com", "b@example.com"]):
            self.ctx.args = args
            await b.breach_command(self.update, self.ctx)
        self.api.lookup_email.assert_not_called()

    async def test_group_and_blocked_account_do_not_query(self):
        self.msg.chat.type = "group"
        await b.breach_command(self.update, self.ctx)
        self.msg.chat.type = "private"
        UserRepo.upsert(123, "test", "test")
        UserRepo.set_blocked(123, True)
        await b.breach_command(self.update, self.ctx)
        self.api.lookup_email.assert_not_called()

    async def test_plain_email_is_consumed_before_other_handlers(self):
        with self.assertRaises(ApplicationHandlerStop):
            await b.receive_email(self.update, self.ctx)
        self.api.lookup_email.assert_awaited_once()

    async def test_support_admin_and_instagram_text_is_preserved(self):
        for flag in b._OTHER_INPUTS:
            self.ctx.user_data = {flag: True}
            await b.receive_email(self.update, self.ctx)
        self.api.lookup_email.assert_not_called()

    async def test_payment_evidence_is_preserved(self):
        with patch.object(b.OrderRepo, "get_latest_awaiting_payment", return_value={"id": 1}):
            await b.receive_email(self.update, self.ctx)
        self.api.lookup_email.assert_not_called()

    async def test_explicit_email_mode_overrides_pending_payment(self):
        self.ctx.user_data["awaiting_breach_email"] = True
        with patch.object(b.OrderRepo, "get_latest_awaiting_payment", return_value={"id": 1}):
            with self.assertRaises(ApplicationHandlerStop):
                await b.receive_email(self.update, self.ctx)
        self.api.lookup_email.assert_awaited_once()
        self.assertNotIn("awaiting_breach_email", self.ctx.user_data)

    async def test_invalid_prompt_keeps_waiting(self):
        self.ctx.user_data["awaiting_breach_email"] = True
        self.msg.text = "not-an-email"
        with self.assertRaises(ApplicationHandlerStop):
            await b.receive_email(self.update, self.ctx)
        self.assertTrue(self.ctx.user_data["awaiting_breach_email"])
        self.api.lookup_email.assert_not_called()

    async def test_api_failure_is_distinct_from_zero_result(self):
        self.ctx.user_data["awaiting_breach_email"] = True
        self.api.lookup_email.side_effect = LeakCheckUnavailable("rate_limit")
        with self.assertRaises(ApplicationHandlerStop):
            await b.receive_email(self.update, self.ctx)
        self.assertIn("در دسترس نیست", self.msg.reply_text.call_args.args[0])
        self.assertTrue(self.ctx.user_data["awaiting_breach_email"])
        empty = b.format_summary("person@example.com", BreachSummary(0, (), ()))
        self.assertIn("رکوردی پیدا نشد", empty)

    async def test_cooldown_limits_repeated_queries(self):
        await b.breach_command(self.update, self.ctx)
        await b.breach_command(self.update, self.ctx)
        self.api.lookup_email.assert_awaited_once()
        self.assertIn("۵ ثانیه", self.msg.reply_text.call_args.args[0])

    async def test_menu_and_inline_navigation_cancel_prompt(self):
        self.ctx.user_data["awaiting_breach_email"] = True
        self.msg.text = "📩 پشتیبانی"
        await b.receive_email(self.update, self.ctx)
        self.assertNotIn("awaiting_breach_email", self.ctx.user_data)
        self.ctx.user_data["awaiting_breach_email"] = True
        await b.clear_pending_email(self.update, self.ctx)
        self.assertNotIn("awaiting_breach_email", self.ctx.user_data)

    async def test_inline_email_button_prompts(self):
        self.update.callback_query = SimpleNamespace(answer=AsyncMock())
        await b.email_prompt_callback(self.update, self.ctx)
        self.update.callback_query.answer.assert_awaited_once()
        self.assertTrue(self.ctx.user_data["awaiting_breach_email"])

    def test_email_buttons_are_present(self):
        self.assertTrue(any(x.text == b.EMAIL_BUTTON for row in _persistent_keyboard().keyboard for x in row))
        self.assertTrue(any(x.callback_data == "menu:email" for row in _inline_main_menu().inline_keyboard for x in row))


class APITests(unittest.IsolatedAsyncioTestCase):
    async def test_only_metadata_is_returned(self):
        def handler(request):
            self.assertEqual(request.url.params["check"], "person@example.com")
            return httpx.Response(200, json={"success": True, "found": 1,
                "fields": ["email"], "sources": [{"name": "Example", "date": "2020-01"}],
                "result": [{"password": "FAKE_SECRET_NEVER_DISPLAY"}]})
        api = LeakCheckPublic(transport=httpx.MockTransport(handler))
        try:
            result = await api.lookup_email("person@example.com")
            self.assertEqual(result.found, 1)
            self.assertNotIn("FAKE_SECRET_NEVER_DISPLAY", repr(result))
        finally:
            await api.close()

    async def test_zero_malformed_and_rate_limited_responses(self):
        for response, success in (
            (httpx.Response(200, json={"success": True, "found": 0, "fields": [], "sources": []}), True),
            (httpx.Response(429), False),
            (httpx.Response(200, json={"success": False}), False),
            (httpx.Response(200, text="not json"), False),
        ):
            api = LeakCheckPublic(transport=httpx.MockTransport(lambda request: response))
            try:
                if success:
                    self.assertEqual((await api.lookup_email("person@example.com")).found, 0)
                else:
                    with self.assertRaises(LeakCheckUnavailable):
                        await api.lookup_email("person@example.com")
            finally:
                await api.close()


if __name__ == "__main__":
    unittest.main()
