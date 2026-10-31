"""Regressions for immediate rejection and admin-only persisted search history."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import test_single_search_payments as fixtures
from app.db.database import get_connection, init_db
from app.db.repos import UserRepo, OrderRepo, JobRepo, SearchHistoryRepo
from app.services.products import EMAIL_PLAN
from app.services.payment_service import PaymentService
from app.handlers import admin, payments, breach


class RejectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.InterfaceTests.setUp(self)
        self.context.bot = SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock())
        self.query.message = self.msg
        self.msg.photo = [SimpleNamespace(file_id='photo')]
        self.query.edit_message_caption = AsyncMock()
        self.order = PaymentService.create_order(123, EMAIL_PLAN)
        PaymentService.submit_photo_evidence(self.order['order_id'],'photo')
        self.update.effective_user.id=999
        self.query.data='admin_reject:'+self.order['order_id']
    tearDown=fixtures.InterfaceTests.tearDown

    async def test_reject_commits_before_reason_and_never_returns_to_pending(self):
        await payments.admin_reject_callback(self.update,self.context)
        self.assertEqual(OrderRepo.get_by_order_id(self.order['order_id'])['status'],'rejected')
        self.assertEqual(OrderRepo.list_awaiting_review(),[])
        self.assertIsNone(PaymentService.approve_order(self.order['order_id'],999))
        self.context.user_data.clear()  # Restart or abandoned reason does not undo rejection.
        await admin._show_pending_orders(self.update,self.context)
        self.context.bot.send_photo.assert_not_awaited()
        self.assertIn('هیچ سفارش',self.query.edit_message_text.call_args.args[0])

    async def test_legacy_reject_button_also_commits_immediately(self):
        self.query.data='adm_reject:'+self.order['order_id']
        await admin.admin_callback(self.update,self.context)
        self.assertEqual(OrderRepo.count_by_status('awaiting_review'),0)
        self.assertEqual(OrderRepo.count_by_status('rejected'),1)

    async def test_duplicate_rejection_has_no_second_notification(self):
        await payments.admin_reject_callback(self.update,self.context)
        await payments.admin_reject_callback(self.update,self.context)
        self.context.bot.send_message.assert_awaited_once()
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'],0)

    async def test_paid_order_cannot_be_rejected(self):
        PaymentService.approve_order(self.order['order_id'],999)
        await payments.admin_reject_callback(self.update,self.context)
        self.assertEqual(OrderRepo.get_by_order_id(self.order['order_id'])['status'],'paid')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'],1)

    async def test_non_admin_cannot_reject(self):
        self.update.effective_user.id=123
        await payments.admin_reject_callback(self.update,self.context)
        self.assertEqual(OrderRepo.get_by_order_id(self.order['order_id'])['status'],'awaiting_review')

    async def test_reason_overrides_stale_admin_input_without_reopening_order(self):
        self.context.user_data['adm_await']='search_id'
        await payments.admin_reject_callback(self.update,self.context)
        self.assertNotIn('adm_await',self.context.user_data)
        self.query.data='admin_reject_reason:'+self.order['order_id']
        await payments.admin_reject_reason_callback(self.update,self.context)
        self.msg.text='bad [*_] receipt'
        self.context.user_data['adm_await']='search_id'
        from app.main import _route_text
        with patch('app.main.admin_text_handler') as wrong_route:
            await _route_text(self.update,self.context)
        wrong_route.assert_not_awaited()
        order=OrderRepo.get_by_order_id(self.order['order_id'])
        self.assertEqual((order['status'],order['admin_note']),('rejected','bad [*_] receipt'))
        self.assertEqual(OrderRepo.list_awaiting_review(),[])

    async def test_cancel_reason_does_not_cancel_committed_rejection(self):
        await payments.admin_reject_callback(self.update,self.context)
        self.query.data='admin_reject_reason:'+self.order['order_id']
        await payments.admin_reject_reason_callback(self.update,self.context)
        from app.handlers.start import main_menu_callback
        self.update.callback_query=None
        await main_menu_callback(self.update,self.context)
        self.assertNotIn('rejecting_order_id',self.context.user_data)
        self.assertEqual(OrderRepo.get_by_order_id(self.order['order_id'])['status'],'rejected')


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown

    async def test_combined_history_has_instagram_and_email_with_statuses(self):
        job=JobRepo.create(123,'some_user.name')
        JobRepo.finish(job['id'],'summary')
        search=SearchHistoryRepo.start_email(123,'my_user@example.com')
        SearchHistoryRepo.finish_email(search,'failed')
        rows=SearchHistoryRepo.page(123)
        self.assertEqual({(r['service'],r['target'],r['status']) for r in rows},
            {('instagram','some_user.name','done'),('email','my_user@example.com','failed')})
        self.update.effective_user.id=999
        self.query.data='adm_jobs:123'
        await admin.admin_callback(self.update,self.context)
        text=self.query.edit_message_text.call_args.args[0]
        self.assertIn('some_user.name',text)
        self.assertIn('my_user@example.com',text)
        self.assertIsNone(self.query.edit_message_text.call_args.kwargs['parse_mode'])

    async def test_history_is_admin_only(self):
        SearchHistoryRepo.start_email(123,'private@example.com')
        self.query.data='adm_jobs:123'
        await admin.admin_callback(self.update,self.context)
        self.query.edit_message_text.assert_not_awaited()
        self.query.answer.assert_awaited_once_with('⛔ دسترسی ندارید.',show_alert=True)

    async def test_pagination_is_stable_and_user_scoped(self):
        UserRepo.upsert(456,'other','Other')
        SearchHistoryRepo.start_email(456,'other@example.com')
        for i in range(12):SearchHistoryRepo.start_email(123,f'user{i}@example.com')
        first=SearchHistoryRepo.page(123,limit=10)
        second=SearchHistoryRepo.page(123,offset=10,limit=10)
        self.assertEqual(len(first),10)
        self.assertEqual(len(second),2)
        self.assertFalse({r['id'] for r in first}&{r['id'] for r in second})
        self.update.effective_user.id=999
        self.query.data='adm_jobs:123:1'
        await admin.admin_callback(self.update,self.context)
        text=self.query.edit_message_text.call_args.args[0]
        self.assertIn('صفحه 2',text)
        self.assertNotIn('other@example.com',text)

    async def test_migration_preserves_users_balances_and_old_jobs(self):
        JobRepo.create(123,'legacy_target')
        with get_connection() as conn:
            conn.execute('DROP TABLE email_searches')
            conn.execute('UPDATE users SET email_credits=4,instagram_credits=5 WHERE telegram_user_id=123')
        from app.db import database
        path=database._DB_PATH
        init_db(path)
        init_db(path)
        self.assertEqual(len(SearchHistoryRepo.page(123)),1)
        user=UserRepo.get_by_telegram_id(123)
        self.assertEqual((user['email_credits'],user['instagram_credits']),(4,5))
        SearchHistoryRepo.start_email(123,'new@example.com')
        with get_connection() as conn:conn.execute('DELETE FROM jobs WHERE telegram_user_id=123');conn.execute('DELETE FROM users WHERE telegram_user_id=123')
        self.assertEqual(SearchHistoryRepo.page(123),[])


class EmailHistoryTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.EmailBillingTests.setUp
    tearDown=fixtures.EmailBillingTests.tearDown

    async def test_success_and_zero_results_are_logged(self):
        from app.services.leakcheck_public import BreachSummary
        self.api.lookup_email.return_value=BreachSummary(0,(),())
        await breach.breach_command(self.update,self.ctx)
        rows=SearchHistoryRepo.page(123)
        self.assertEqual([(r['target'],r['status']) for r in rows],[('person@example.com','done')])

    async def test_failed_provider_is_logged_and_refunded(self):
        from app.services.leakcheck_public import LeakCheckUnavailable
        self.api.lookup_email.side_effect=LeakCheckUnavailable('test')
        await breach.breach_command(self.update,self.ctx)
        self.assertEqual(SearchHistoryRepo.page(123)[0]['status'],'failed')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'],1)

    async def test_invalid_email_is_not_logged(self):
        self.ctx.args=['invalid']
        await breach.breach_command(self.update,self.ctx)
        self.assertEqual(SearchHistoryRepo.page(123),[])

    async def test_no_credit_is_not_logged(self):
        with get_connection() as conn:conn.execute('UPDATE users SET email_credits=0')
        await breach.breach_command(self.update,self.ctx)
        self.assertEqual(SearchHistoryRepo.page(123),[])

    async def test_audit_failure_still_refunds_before_any_provider_request(self):
        with patch.object(SearchHistoryRepo,'start_email',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):await breach.breach_command(self.update,self.ctx)
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'],1)
        self.api.lookup_email.assert_not_awaited()
