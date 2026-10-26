"""Checkout recovery regressions: real SQLite with mocked Telegram delivery."""
import concurrent.futures
import unittest
from unittest.mock import patch
import test_single_search_payments as fixtures
from app.db.database import get_connection
from app.db.repos import UserRepo, OrderRepo
from app.services.products import EMAIL_PLAN, INSTAGRAM_PLAN
from app.services.payment_service import PaymentService
from app.handlers.plans import buy_plan_callback, orders_handler, order_view
from app.handlers.payments import receive_evidence_handler


class OrderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.InterfaceTests.setUp(self)
        self.query.message = self.msg
        self.msg.text = 'receipt-123'
        self.msg.photo = []

    tearDown = fixtures.InterfaceTests.tearDown

    def buttons(self):
        return [b for row in self.query.edit_message_text.call_args.kwargs['reply_markup'].inline_keyboard for b in row]

    async def test_other_product_open_order_shows_payment_and_explicit_switch(self):
        old = PaymentService.create_order(123, INSTAGRAM_PLAN)
        self.query.data = 'buy:' + EMAIL_PLAN
        await buy_plan_callback(self.update, self.context)
        text = self.query.edit_message_text.call_args.args[0]
        self.assertIn('شماره کارت', text)
        self.assertIn('299,000', text)
        self.assertIn('سرویس دیگری', text)
        self.assertIn(old['order_id'], text)
        self.assertTrue(any(b.callback_data == f"orders:switch:{old['order_id']}:{EMAIL_PLAN}" for b in self.buttons()))
        self.assertEqual(len(OrderRepo.get_open(123)), 1)

    async def test_same_product_reopens_checkout_without_duplicate_order(self):
        order = PaymentService.create_order(123, EMAIL_PLAN)
        self.query.data = 'buy:' + EMAIL_PLAN
        await buy_plan_callback(self.update, self.context)
        self.assertIn('شماره کارت', self.query.edit_message_text.call_args.args[0])
        self.assertEqual(self.context.user_data['pending_order_id'], order['order_id'])
        self.assertEqual(len(OrderRepo.get_open(123)), 1)

    async def test_receipt_under_review_shows_status_and_prevents_second_payment(self):
        order = PaymentService.create_order(123, INSTAGRAM_PLAN)
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        self.query.data = 'buy:' + EMAIL_PLAN
        await buy_plan_callback(self.update, self.context)
        text = self.query.edit_message_text.call_args.args[0]
        self.assertIn('دوباره واریز نکنید', text)
        self.assertNotIn('شماره کارت', text)
        self.assertFalse(any(b.callback_data.startswith(('orders:switch:', 'cancel_order:')) for b in self.buttons()))
        self.assertTrue(any(b.callback_data == 'menu:support' for b in self.buttons()))

    async def test_explicit_switch_replaces_only_unpaid_order(self):
        old = PaymentService.create_order(123, INSTAGRAM_PLAN)
        self.query.data = f"orders:switch:{old['order_id']}:{EMAIL_PLAN}"
        await orders_handler(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(old['order_id'])['status'], 'expired')
        new = OrderRepo.get_open(123)
        self.assertEqual(len(new), 1)
        self.assertEqual((new[0]['plan_code'], new[0]['amount_toman']), (EMAIL_PLAN, 199000))
        self.assertEqual(self.context.user_data['pending_order_id'], new[0]['order_id'])
        self.assertIn('199,000', self.query.edit_message_text.call_args.args[0])

    async def test_switch_cannot_cancel_another_users_order(self):
        old = PaymentService.create_order(123, INSTAGRAM_PLAN)
        self.update.effective_user.id = 456
        self.query.data = f"orders:switch:{old['order_id']}:{EMAIL_PLAN}"
        await orders_handler(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(old['order_id'])['status'], 'awaiting_payment')
        self.assertEqual(OrderRepo.get_open(456), [])
        self.assertNotIn('شماره کارت', self.query.edit_message_text.call_args.args[0])

    async def test_stale_switch_after_receipt_keeps_reviewed_order(self):
        old = PaymentService.create_order(123, INSTAGRAM_PLAN)
        PaymentService.submit_text_evidence(old['order_id'], 'receipt-test')
        self.query.data = f"orders:switch:{old['order_id']}:{EMAIL_PLAN}"
        await orders_handler(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(old['order_id'])['status'], 'awaiting_review')
        self.assertEqual(len(OrderRepo.get_open(123)), 1)

    async def test_legacy_inactive_order_can_still_show_payment(self):
        from app.db.repos import PlanRepo
        PlanRepo.upsert('LEGACY', 'Legacy', 499000, 3, 30, 0)
        old = OrderRepo.create(123, 'LEGACY', 499000)
        self.query.data = 'buy:' + EMAIL_PLAN
        await buy_plan_callback(self.update, self.context)
        self.assertIn('499,000', self.query.edit_message_text.call_args.args[0])
        self.assertIn(old['order_id'], self.query.edit_message_text.call_args.args[0])

    async def test_ordinary_user_can_route_support_from_checkout(self):
        from app.main import _route_text
        self.context.user_data['awaiting_support_message'] = True
        with patch('app.main.receive_support_message') as support:
            await _route_text(self.update, self.context)
        support.assert_awaited_once()

    async def test_orders_survive_new_context_and_list_has_resume_action(self):
        old = PaymentService.create_order(123, EMAIL_PLAN)
        self.context.user_data.clear()
        self.query.data = 'orders:list'
        await orders_handler(self.update, self.context)
        self.assertTrue(any(b.callback_data == f"orders:view:{old['order_id']}" for b in self.buttons()))
        self.query.data = f"orders:view:{old['order_id']}"
        await orders_handler(self.update, self.context)
        self.assertIn('شماره کارت', self.query.edit_message_text.call_args.args[0])

    async def test_receipt_uses_selected_legacy_order_not_unrelated_latest(self):
        old = PaymentService.create_order(123, EMAIL_PLAN)
        # Simulate a pre-upgrade database with multiple unpaid orders.
        with get_connection() as conn:
            conn.execute("INSERT INTO orders (order_id,telegram_user_id,plan_code,amount_toman,created_at,updated_at) VALUES ('ORD-OTHER',123,?,299000,'2026','2026')", (INSTAGRAM_PLAN,))
        self.context.user_data['pending_order_id'] = old['order_id']
        with patch('app.handlers.payments._notify_admins'):
            await receive_evidence_handler(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(old['order_id'])['status'], 'awaiting_review')
        self.assertEqual(OrderRepo.get_by_order_id('ORD-OTHER')['status'], 'awaiting_payment')

    async def test_stale_selected_order_does_not_accept_receipt_for_other_order(self):
        order = PaymentService.create_order(123, EMAIL_PLAN)
        self.context.user_data['pending_order_id'] = order['order_id']
        PaymentService.submit_text_evidence(order['order_id'], 'receipt-test')
        await receive_evidence_handler(self.update, self.context)
        self.assertIn('/orders', self.msg.reply_text.call_args.args[0])

    async def test_receipt_and_switch_are_serialized(self):
        order = PaymentService.create_order(123, INSTAGRAM_PLAN)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            switch = pool.submit(OrderRepo.switch_unpaid, order['order_id'], 123, EMAIL_PLAN)
            receipt = pool.submit(PaymentService.submit_text_evidence, order['order_id'], 'receipt-test')
            new, accepted = switch.result(), receipt.result()
        if new:
            self.assertFalse(accepted)
            self.assertEqual(OrderRepo.get_by_order_id(order['order_id'])['status'], 'expired')
        else:
            self.assertTrue(accepted)
            self.assertEqual(OrderRepo.get_by_order_id(order['order_id'])['status'], 'awaiting_review')

    async def test_new_menu_labels_do_not_get_consumed_as_email_or_receipt(self):
        from app.handlers.breach import receive_email
        from app.handlers.start import reply_keyboard_router
        from app.utils.keyboards import INSTAGRAM_BUTTON, ORDERS_BUTTON
        self.update.callback_query = None
        for label in (INSTAGRAM_BUTTON, ORDERS_BUTTON):
            self.msg.text = label
            self.context.user_data['awaiting_breach_email'] = True
            await receive_email(self.update, self.context)
            self.assertNotIn('awaiting_breach_email', self.context.user_data)
            self.assertTrue(await reply_keyboard_router(self.update, self.context))

    def test_callback_lengths_and_html_escape(self):
        order = PaymentService.create_order(123, INSTAGRAM_PLAN)
        text, keyboard = order_view(order, EMAIL_PLAN)
        self.assertTrue(all(len(b.callback_data.encode()) <= 64 for row in keyboard.inline_keyboard for b in row))
        from types import SimpleNamespace
        with patch('app.handlers.plans.config', SimpleNamespace(payment_card_number='123<456', payment_card_holder='A&B')):
            text, _ = order_view(order)
        self.assertIn('123&lt;456', text)
        self.assertIn('A&amp;B', text)

    async def test_refresh_of_unchanged_status_is_harmless(self):
        from telegram.error import BadRequest
        old = PaymentService.create_order(123, EMAIL_PLAN)
        PaymentService.submit_text_evidence(old['order_id'], 'receipt-test')
        self.query.data = f"orders:view:{old['order_id']}"
        self.query.edit_message_text.side_effect = BadRequest('Message is not modified')
        await orders_handler(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(old['order_id'])['status'], 'awaiting_review')

    async def test_other_telegram_errors_are_not_silenced(self):
        from telegram.error import BadRequest
        old = PaymentService.create_order(123, EMAIL_PLAN)
        self.query.data = f"orders:view:{old['order_id']}"
        self.query.edit_message_text.side_effect = BadRequest('Chat not found')
        with self.assertRaises(BadRequest):
            await orders_handler(self.update, self.context)
