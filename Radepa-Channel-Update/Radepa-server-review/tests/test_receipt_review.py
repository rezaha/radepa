"""Payment receipt integration: temporary SQLite and mocked Telegram, no messages sent."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from telegram.error import BadRequest
import test_single_search_payments as fixtures
from app.db.repos import OrderRepo, UserRepo
from app.services.products import EMAIL_PLAN
from app.services.payment_service import PaymentService
from app.services.receipt_review import send_order_review
from app.handlers import payments, admin


class ReceiptReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.InterfaceTests.setUp(self)
        self.context.bot = SimpleNamespace(send_photo=AsyncMock(), send_document=AsyncMock(), send_message=AsyncMock())
        self.msg.photo = []
        self.msg.document = None
        self.msg.text = None
        self.query.message = self.msg
        self.query.edit_message_caption = AsyncMock()
        self.order = PaymentService.create_order(123, EMAIL_PLAN)

    tearDown = fixtures.InterfaceTests.tearDown

    def photo_order(self):
        PaymentService.submit_photo_evidence(self.order['order_id'], 'telegram-photo-id')
        return OrderRepo.get_by_order_id(self.order['order_id'])

    async def test_uploaded_photo_is_persisted_and_sent_to_admin_with_controls(self):
        self.context.user_data['pending_order_id'] = self.order['order_id']
        self.msg.photo = [SimpleNamespace(file_id='small'), SimpleNamespace(file_id='large')]
        await payments.receive_evidence_handler(self.update, self.context)
        stored = OrderRepo.get_by_order_id(self.order['order_id'])
        self.assertEqual((stored['evidence_type'], stored['evidence_file_id']), ('photo', 'large'))
        sent = self.context.bot.send_photo.call_args.kwargs
        self.assertEqual((sent['chat_id'], sent['photo']), (999, 'large'))
        self.assertIn(self.order['order_id'], sent['caption'])
        self.assertIn('199,000', sent['caption'])
        actions = [b.callback_data for row in sent['reply_markup'].inline_keyboard for b in row]
        self.assertIn('admin_approve:' + self.order['order_id'], actions)
        self.assertIn('admin_reject:' + self.order['order_id'], actions)

    async def test_pending_admin_panel_resends_stored_photo_after_context_reset(self):
        self.photo_order()
        self.context.user_data.clear()
        self.update.effective_user.id = 999
        await admin._show_pending_orders(self.update, self.context)
        self.context.bot.send_photo.assert_awaited_once()
        self.assertEqual(self.context.bot.send_photo.call_args.kwargs['photo'], 'telegram-photo-id')
        self.assertIn('1 سفارش از 1', self.query.edit_message_text.call_args.args[0])

    async def test_details_callback_retrieves_photo_from_database(self):
        self.photo_order()
        self.update.effective_user.id = 999
        self.query.data = 'admin_order_detail:' + self.order['order_id']
        await payments.admin_order_detail_callback(self.update, self.context)
        self.context.bot.send_photo.assert_awaited_once()

    async def test_legacy_panel_details_retrieves_photo(self):
        self.photo_order()
        self.update.effective_user.id = 999
        self.query.data = 'adm_odetail:' + self.order['order_id']
        await admin.admin_callback(self.update, self.context)
        self.context.bot.send_photo.assert_awaited_once()

    async def test_non_admin_cannot_view_receipt(self):
        self.photo_order()
        self.query.data = 'admin_order_detail:' + self.order['order_id']
        await payments.admin_order_detail_callback(self.update, self.context)
        self.context.bot.send_photo.assert_not_awaited()
        self.query.answer.assert_awaited_once_with(payments.ADMIN_ONLY, show_alert=True)

    async def test_approve_from_photo_edits_caption_and_grants_only_once(self):
        self.photo_order()
        self.msg.photo = [SimpleNamespace(file_id='telegram-photo-id')]
        self.update.effective_user.id = 999
        self.query.data = 'admin_approve:' + self.order['order_id']
        await payments.admin_approve_callback(self.update, self.context)
        self.query.edit_message_caption.assert_awaited_once()
        self.query.edit_message_text.assert_not_awaited()
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'], 1)
        self.assertEqual(self.context.bot.send_message.call_args.kwargs['chat_id'], 123)
        await payments.admin_approve_callback(self.update, self.context)
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'], 1)

    async def test_reject_from_photo_prompts_via_caption_then_rejects(self):
        self.photo_order()
        self.msg.photo = [SimpleNamespace(file_id='telegram-photo-id')]
        self.update.effective_user.id = 999
        self.query.data = 'admin_reject:' + self.order['order_id']
        await payments.admin_reject_callback(self.update, self.context)
        self.query.edit_message_caption.assert_awaited_once()
        self.msg.text = 'receipt not readable'
        await payments.admin_reject_note_handler(self.update, self.context)
        self.assertEqual(OrderRepo.get_by_order_id(self.order['order_id'])['status'], 'rejected')
        self.assertEqual(UserRepo.get_by_telegram_id(123)['email_credits'], 0)

    async def test_receipt_as_image_document_is_preserved_and_delivered(self):
        self.msg.document = SimpleNamespace(file_id='image-document-id', mime_type='image/png')
        await payments.receive_evidence_handler(self.update, self.context)
        stored = OrderRepo.get_by_order_id(self.order['order_id'])
        self.assertEqual((stored['evidence_type'], stored['evidence_file_id']), ('document','image-document-id'))
        self.context.bot.send_document.assert_awaited_once()
        self.assertEqual(self.context.bot.send_document.call_args.kwargs['document'], 'image-document-id')

    async def test_text_receipt_and_markup_characters_are_literal(self):
        UserRepo.upsert(123, 'user_with_underscores', 'Name [test] * _')
        PaymentService.submit_text_evidence(self.order['order_id'], 'transaction [*_]')
        await send_order_review(self.context.bot,999,OrderRepo.get_by_order_id(self.order['order_id']))
        sent=self.context.bot.send_message.call_args.kwargs
        self.assertIsNone(sent['parse_mode'])
        self.assertIn('Name [test] * _', sent['text'])
        self.assertIn('transaction [*_]', sent['text'])

    async def test_long_names_do_not_break_telegram_photo_caption_limit(self):
        UserRepo.upsert(123, 'x'*200, '😀'*1000)
        await send_order_review(self.context.bot,999,self.photo_order())
        caption=self.context.bot.send_photo.call_args.kwargs['caption']
        self.assertLessEqual(len(caption.encode('utf-16-le'))//2,950)
        self.assertIn(self.order['order_id'],caption)

    async def test_photo_delivery_failure_keeps_order_visible_and_pending(self):
        self.context.bot.send_photo.side_effect=BadRequest('File not found')
        sent = await send_order_review(self.context.bot,999,self.photo_order())
        self.assertFalse(sent)
        self.assertIn('ناموفق',self.context.bot.send_message.call_args.kwargs['text'])
        self.assertEqual(OrderRepo.get_by_order_id(self.order['order_id'])['status'],'awaiting_review')

    async def test_pending_panel_reports_actual_delivery_count(self):
        self.photo_order()
        self.update.effective_user.id=999
        self.context.bot.send_photo.side_effect=BadRequest('failed')
        self.context.bot.send_message.side_effect=BadRequest('failed')
        await admin._show_pending_orders(self.update,self.context)
        self.assertIn('0 سفارش از 1',self.query.edit_message_text.call_args.args[0])
