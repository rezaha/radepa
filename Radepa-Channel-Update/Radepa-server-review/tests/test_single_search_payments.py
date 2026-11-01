"""Offline billing integration tests using real temporary SQLite transactions."""
import asyncio
import concurrent.futures
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {"BOT_TOKEN": "123456:offline-test-token", "ADMIN_IDS": "999",
                   "PAYMENT_CARD_NUMBER": "test", "PAYMENT_CARD_HOLDER": "test",
                   "SERPER_API_KEY": "offline-test-key"}.items():
    os.environ.setdefault(key, value)

from app.db.database import init_db, get_connection
from app.db.repos import UserRepo, PlanRepo, OrderRepo
from app.services.products import EMAIL_PLAN, INSTAGRAM_PLAN, seed_products
from app.services.payment_service import PaymentService
from app.services.credit_service import CreditService
from app.services.subscription_service import SubscriptionService
from app.services.job_service import JobService
from app.services.leakcheck_public import BreachSummary, LeakCheckUnavailable
from app.services.email_report import render_html, render_txt
from app.handlers import breach
from telegram.error import TimedOut


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'billing.db')
        init_db(self.path)
        seed_products()
        UserRepo.upsert(123, 'test', 'Test')

    def tearDown(self):
        self.temp.cleanup()

    def balance(self):
        return UserRepo.get_by_telegram_id(123)

    def grant(self, code):
        order = PaymentService.create_order(123, code)
        self.assertIsNotNone(order)
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        return PaymentService.approve_order(order['order_id'], 999), order['order_id']

    def test_catalog_prices_and_single_search_without_expiry(self):
        plans = PlanRepo.get_active()
        self.assertEqual({p['plan_code']: p['price_toman'] for p in plans},
                         {EMAIL_PLAN: 199000, INSTAGRAM_PLAN: 299000})
        self.assertTrue(all(p['credits'] == 1 and p['duration_days'] == 0 for p in plans))

    def test_approval_grants_correct_service_once(self):
        result, order_id = self.grant(EMAIL_PLAN)
        self.assertEqual(result['credits'], 1)
        self.assertIsNone(result['expire_iso'])
        self.assertIsNone(PaymentService.approve_order(order_id, 999))
        self.assertEqual(self.balance()['email_credits'], 1)
        self.assertEqual(self.balance()['instagram_credits'], 0)
        self.assertEqual(self.balance()['credits'], 0)
        self.grant(INSTAGRAM_PLAN)
        self.assertEqual(self.balance()['instagram_credits'], 1)
        self.assertTrue(SubscriptionService.check_can_analyze(123)[0])

    def test_concurrent_approval_grants_only_once(self):
        order = PaymentService.create_order(123, EMAIL_PLAN)
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: PaymentService.approve_order(order['order_id'], 999), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.balance()['email_credits'], 1)

    def test_cannot_approve_without_evidence_or_after_rejection(self):
        order = PaymentService.create_order(123, EMAIL_PLAN)
        self.assertIsNone(PaymentService.approve_order(order['order_id'], 999))
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        PaymentService.reject_order(order['order_id'], 999)
        self.assertIsNone(PaymentService.approve_order(order['order_id'], 999))
        self.assertEqual(self.balance()['email_credits'], 0)

    def test_pending_order_reused_and_other_product_blocked(self):
        order = PaymentService.create_order(123, EMAIL_PLAN)
        self.assertEqual(PaymentService.create_order(123, EMAIL_PLAN)['order_id'], order['order_id'])
        self.assertIsNone(PaymentService.create_order(123, INSTAGRAM_PLAN))
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        self.assertIsNone(PaymentService.create_order(123, EMAIL_PLAN))

    def test_independent_balances_and_idempotent_refund(self):
        self.grant(EMAIL_PLAN)
        self.assertIsNone(CreditService.reserve(123, 'instagram'))
        charge = CreditService.reserve(123, 'email')
        self.assertIsNotNone(charge)
        self.assertIsNone(CreditService.reserve(123, 'email'))
        self.assertTrue(CreditService.refund(charge))
        self.assertFalse(CreditService.refund(charge))
        self.assertEqual(self.balance()['email_credits'], 1)
        charge = CreditService.reserve(123, 'email')
        CreditService.complete(charge)
        self.assertFalse(CreditService.refund(charge))
        self.assertEqual(self.balance()['email_credits'], 0)

    def test_concurrent_reservation_and_startup_recovery(self):
        self.grant(EMAIL_PLAN)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            charges = list(pool.map(lambda _: CreditService.reserve(123, 'email'), range(2)))
        self.assertEqual(sum(c is not None for c in charges), 1)
        self.assertEqual(CreditService.recover_interrupted(), 1)
        self.assertEqual(CreditService.recover_interrupted(), 0)
        self.assertEqual(self.balance()['email_credits'], 1)

    def test_blocked_accounts_cannot_spend(self):
        self.grant(EMAIL_PLAN)
        UserRepo.set_blocked(123, True)
        self.assertIsNone(CreditService.reserve(123, 'email'))
        self.assertEqual(self.balance()['email_credits'], 1)

    def test_existing_database_migration_and_pending_legacy_order(self):
        # Build the pre-change user table, before init_db adds service balances.
        legacy_path = str(Path(self.temp.name) / 'legacy.db')
        schema = Path('app/db/schema.sql').read_text()
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(schema)
            conn.execute("INSERT INTO users (telegram_user_id, first_name, created_at, last_seen_at, credits, subscription_expire_at) VALUES (123, 'Test', '2026', '2026', 3, '2099-01-01T00:00:00+00:00')")
        init_db(legacy_path)
        init_db(legacy_path)  # Repeatable migration.
        self.assertEqual(self.balance()['credits'], 3)
        self.assertEqual(self.balance()['email_credits'], 0)
        PlanRepo.upsert('FULL_3X', 'Legacy', 499000, 3, 30)
        order = OrderRepo.create(123, 'FULL_3X', 499000)
        OrderRepo.submit_evidence(order['order_id'], 'text', None, 'receipt')
        seed_products()
        self.assertEqual(PlanRepo.get('FULL_3X')['is_active'], 0)
        self.assertIsNotNone(PaymentService.approve_order(order['order_id'], 999))
        self.assertEqual(self.balance()['credits'], 6)
        self.assertEqual(self.balance()['email_credits'], 0)
        charge = CreditService.reserve(123, 'instagram')
        self.assertEqual(self.balance()['credits'], 5)
        CreditService.refund(charge)
        self.assertEqual(self.balance()['credits'], 6)
        with get_connection() as conn:
            conn.execute("UPDATE users SET subscription_expire_at='2000-01-01T00:00:00+00:00'")
        self.assertIsNone(CreditService.reserve(123, 'instagram'))


class EmailBillingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        init_db(str(Path(self.temp.name) / 'email.db'))
        seed_products()
        UserRepo.upsert(123, 'test', 'Test')
        with get_connection() as conn:
            conn.execute('UPDATE users SET email_credits=1, instagram_credits=1 WHERE telegram_user_id=123')
        self.files = []
        async def capture(**kwargs):
            self.files.append((kwargs['filename'], kwargs['document'].getvalue().decode('utf-8')))
        self.msg = SimpleNamespace(chat=SimpleNamespace(type='private'), text='person@example.com',
                                   reply_text=AsyncMock(), reply_document=AsyncMock(side_effect=capture))
        self.update = SimpleNamespace(effective_message=self.msg, effective_user=SimpleNamespace(id=123))
        self.api = SimpleNamespace(lookup_email=AsyncMock(return_value=BreachSummary(1, ('email',), (('Example <Site>', ''),))))
        self.ctx = SimpleNamespace(args=['person@example.com'], user_data={}, bot_data={'leakcheck_public': self.api})

    def tearDown(self):
        self.temp.cleanup()

    def balance(self):
        return UserRepo.get_by_telegram_id(123)['email_credits']

    async def test_success_sends_html_and_utf8_file_and_charges_once(self):
        await breach.breach_command(self.update, self.ctx)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(UserRepo.get_by_telegram_id(123)['instagram_credits'], 1)
        self.msg.reply_document.assert_awaited_once()
        self.assertEqual(self.files[0][0], 'email-security-report.txt')
        self.assertIn('Example <Site>', self.files[0][1])
        self.assertIn('تأیید دومرحله‌ای', self.files[0][1])
        text = self.msg.reply_text.call_args.args[0]
        self.assertIn('Example &lt;Site&gt;', text)
        self.assertNotIn('person@example.com', text)

    async def test_successful_zero_results_consumes_credit(self):
        self.api.lookup_email.return_value = BreachSummary(0, (), ())
        await breach.breach_command(self.update, self.ctx)
        self.assertEqual(self.balance(), 0)
        self.assertIn('رکوردی پیدا نشد', self.msg.reply_text.call_args.args[0])
        self.assertNotIn('⚠️ هشدار:', self.files[0][1])

    async def test_api_failure_refunds_and_sends_no_file(self):
        self.api.lookup_email.side_effect = LeakCheckUnavailable('rate_limit')
        await breach.breach_command(self.update, self.ctx)
        self.assertEqual(self.balance(), 1)
        self.msg.reply_document.assert_not_awaited()

    async def test_delivery_failure_refunds(self):
        self.msg.reply_document.side_effect = TimedOut()
        await breach.breach_command(self.update, self.ctx)
        self.assertEqual(self.balance(), 1)

    async def test_no_credit_or_invalid_input_never_calls_provider(self):
        self.ctx.args = ['invalid']
        await breach.breach_command(self.update, self.ctx)
        self.assertEqual(self.balance(), 1)
        with get_connection() as conn:
            conn.execute('UPDATE users SET email_credits=0')
        self.ctx.args = ['person@example.com']
        await breach.breach_command(self.update, self.ctx)
        self.api.lookup_email.assert_not_awaited()

    async def test_cancellation_refunds(self):
        self.api.lookup_email.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await breach.breach_command(self.update, self.ctx)
        self.assertEqual(self.balance(), 1)

    def test_html_length_and_full_txt_for_large_escaped_sources(self):
        result = BreachSummary(30, ('<' * 64,) * 30, (('<&>' * 33, '2026-01'),) * 30)
        text = render_html('person@example.com', result)
        self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 3900)
        self.assertEqual(render_txt('person@example.com', result).count('• '), 1)


class InstagramBillingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        init_db(str(Path(self.temp.name) / 'instagram.db'))
        UserRepo.upsert(123, 'test', 'Test')
        with get_connection() as conn:
            conn.execute('UPDATE users SET email_credits=2, instagram_credits=1 WHERE telegram_user_id=123')
        self.service = JobService(SimpleNamespace(analyze=AsyncMock(return_value=[])))
        self.service._ddg = SimpleNamespace(analyze=AsyncMock(return_value=[]))
        self.service._serpapi = None
        self.service._google = None

    def tearDown(self):
        self.temp.cleanup()

    async def test_zero_results_charges_instagram_only(self):
        result = await self.service.run_analysis(123, 'example_user')
        self.assertEqual(result['status'], 'ok')
        user = UserRepo.get_by_telegram_id(123)
        self.assertEqual(user['instagram_credits'], 0)
        self.assertEqual(user['email_credits'], 2)
        self.assertEqual((await self.service.run_analysis(123, 'example_user'))['status'], 'no_credit')

    async def test_all_provider_failures_refund(self):
        self.service._serper.analyze.side_effect = RuntimeError('unavailable')
        self.service._ddg.analyze.side_effect = RuntimeError('unavailable')
        result = await self.service.run_analysis(123, 'example_user')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['instagram_credits'], 1)

    async def test_persistence_failure_refunds(self):
        with patch('app.services.job_service.JobRepo.finish', side_effect=sqlite3.OperationalError('test')):
            result = await self.service.run_analysis(123, 'example_user')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['instagram_credits'], 1)

class InterfaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        init_db(str(Path(self.temp.name) / 'ui.db'))
        seed_products()
        UserRepo.upsert(123, 'test', 'Test')
        self.msg = SimpleNamespace(reply_text=AsyncMock(), chat=SimpleNamespace(type='private'))
        self.query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock(), data='menu:plans')
        self.update = SimpleNamespace(effective_user=SimpleNamespace(id=123, username='test', first_name='Test'),
                                      effective_chat=SimpleNamespace(type='private'), callback_query=self.query,
                                      effective_message=self.msg, message=self.msg)
        self.context = SimpleNamespace(user_data={}, bot_data={})

    def tearDown(self):
        self.temp.cleanup()

    async def test_inline_and_reply_plan_menus_offer_both_products(self):
        from app.handlers.plans import show_plans_callback, _send_plans
        await show_plans_callback(self.update, self.context)
        kwargs = self.query.edit_message_text.call_args.kwargs
        buttons = kwargs['reply_markup'].inline_keyboard
        self.assertEqual({row[0].callback_data for row in buttons if row[0].callback_data.startswith('buy:')},
                         {'buy:EMAIL_SINGLE', 'buy:INSTAGRAM_SINGLE'})
        await _send_plans(self.msg, self.context)
        self.assertEqual(self.msg.reply_text.await_count, 1)
        self.assertIn('199,000', self.msg.reply_text.call_args.args[0])
        self.assertIn('299,000', self.msg.reply_text.call_args.args[0])

    async def test_checkout_identifies_product_and_exact_amount(self):
        from app.handlers.plans import buy_plan_callback
        self.query.data = 'buy:EMAIL_SINGLE'
        await buy_plan_callback(self.update, self.context)
        text = self.query.edit_message_text.call_args.args[0]
        self.assertIn('199,000', text)
        self.assertIn('بررسی نشت یک ایمیل', text)
        self.assertIsNotNone(OrderRepo.get_latest_awaiting_payment(123))

    async def test_help_button_cancels_email_prompt(self):
        from app.handlers.start import reply_keyboard_router, HELP_BUTTON
        self.update.callback_query = None
        self.msg.text = HELP_BUTTON
        self.context.user_data['awaiting_breach_email'] = True
        await breach.receive_email(self.update, self.context)
        self.assertTrue(await reply_keyboard_router(self.update, self.context))
        self.assertNotIn('awaiting_breach_email', self.context.user_data)
        self.assertIn('/email', self.msg.reply_text.call_args.args[0])
        self.assertIn('۱۹۹٬۰۰۰', self.msg.reply_text.call_args.args[0])

    async def test_account_shows_both_balances_and_old_credit(self):
        from app.handlers.account import account_text
        text = account_text(UserRepo.get_by_telegram_id(123))
        self.assertIn('اعتبار بررسی ایمیل', text)
        self.assertIn('اعتبار اینستاگرام', text)
        self.assertIn('اعتبار قدیمی', text)

    async def test_admin_confirmation_names_purchased_email_service(self):
        from app.handlers.payments import admin_approve_callback
        order = PaymentService.create_order(123, EMAIL_PLAN)
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        self.update.effective_user.id = 999
        self.query.data = 'admin_approve:' + order['order_id']
        self.context.bot = SimpleNamespace(send_message=AsyncMock())
        await admin_approve_callback(self.update, self.context)
        text = self.context.bot.send_message.call_args.kwargs['text']
        self.assertIn('بررسی نشت یک ایمیل', text)
        self.assertNotIn('آیدی اینستاگرام مورد نظرت', text)

class UnimplementedProviderTests(unittest.IsolatedAsyncioTestCase):
    setUp = InstagramBillingTests.setUp
    tearDown = InstagramBillingTests.tearDown

    async def test_google_stub_cannot_turn_outage_into_paid_zero_result(self):
        from app.services.google_cse_service import GoogleCSEService
        self.service._serper.analyze.side_effect = RuntimeError('unavailable')
        self.service._ddg.analyze.side_effect = RuntimeError('unavailable')
        self.service._google = GoogleCSEService('test', 'test')
        with patch('app.services.job_service.config', SimpleNamespace(google_api_key='test')):
            result = await self.service.run_analysis(123, 'example_user')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['instagram_credits'], 1)

class ReceiptRaceTests(unittest.IsolatedAsyncioTestCase):
    setUp = InterfaceTests.setUp
    tearDown = InterfaceTests.tearDown

    async def test_cancel_cannot_overwrite_receipt_submitted_during_read(self):
        from app.handlers.payments import cancel_order_callback
        order = PaymentService.create_order(123, EMAIL_PLAN)
        self.query.data = 'cancel_order:' + order['order_id']
        def stale_read(order_id):
            # Simulate another worker accepting the receipt after the read.
            with get_connection() as conn:
                conn.execute("UPDATE orders SET status='awaiting_review' WHERE order_id=?", (order_id,))
            return order
        with patch.object(OrderRepo, 'get_by_order_id', side_effect=stale_read):
            await cancel_order_callback(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(order['order_id'])['status'], 'awaiting_review')
        self.assertNotIn('لغو شد', self.query.edit_message_text.call_args.args[0])

    async def test_concurrent_receipts_are_accepted_only_once(self):
        order = PaymentService.create_order(123, EMAIL_PLAN)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            accepted = list(pool.map(lambda _: PaymentService.submit_text_evidence(order['order_id'], 'receipt-test'), range(2)))
        self.assertEqual(accepted.count(True), 1)
        self.assertEqual(OrderRepo.get_by_order_id(order['order_id'])['status'], 'awaiting_review')


class ProviderResponseTests(unittest.IsolatedAsyncioTestCase):
    setUp = InstagramBillingTests.setUp
    tearDown = InstagramBillingTests.tearDown

    async def test_cancelled_providers_are_not_a_paid_empty_result(self):
        self.service._serper.analyze.side_effect = asyncio.CancelledError()
        self.service._ddg.analyze.side_effect = asyncio.CancelledError()
        result = await self.service.run_analysis(123, 'example_user')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['instagram_credits'], 1)

    async def test_invalid_provider_results_refund(self):
        self.service._serper.analyze.return_value = None
        self.service._ddg.analyze.return_value = {'error': 'unavailable'}
        result = await self.service.run_analysis(123, 'example_user')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['instagram_credits'], 1)


class SourceDateTests(unittest.IsolatedAsyncioTestCase):
    async def test_sources_with_missing_dates_still_appear_in_reports(self):
        import httpx
        from app.services.leakcheck_public import LeakCheckPublic
        def handler(request):
            return httpx.Response(200, json={'success': True, 'found': 2, 'fields': ['email'],
                'sources': [{'name': 'Source A', 'date': None}, {'name': 'Source B'}]})
        api = LeakCheckPublic(transport=httpx.MockTransport(handler))
        try:
            result = await api.lookup_email('person@example.com')
        finally:
            await api.close()
        self.assertEqual(result.sources, (('Source A', ''), ('Source B', '')))
        report = render_txt('person@example.com', result)
        self.assertIn('Source A', report)
        self.assertIn('نامشخص', report)
