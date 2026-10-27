"""Synthetic provider responses; no external network or real identifiers."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
from app.services.abstract_email import AbstractEmail, AbstractUnavailable, parse_summary
from app.services.email_lookup import EmailSummary
from app.services.email_report import render_html, render_txt
from app.services.leakcheck_public import BreachSummary, LeakCheckUnavailable
import test_single_search_payments as fixtures
from app.handlers import breach

PAYLOAD = {
    'email_risk': {'address_risk_status': 'low', 'domain_risk_status': 'low'},
    'email_quality': {'score': 0.95, 'is_disposable_email': False},
    'email_deliverability': {'status': 'deliverable', 'is_smtp_valid': True},
    'email_breaches': {'total_breaches': 3, 'breached_domains': ['Example.com', ' example.COM ', 'Other.org']},
    'raw_records': [{'password': 'NEVER_DISPLAY'}],
}

class AbstractAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_get_bearer_and_metadata_only(self):
        def handler(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(str(request.url).split('?')[0], 'https://emailreputation.abstractapi.com/v1/')
            self.assertEqual(dict(request.url.params), {'email': 'person@example.com'})
            self.assertEqual(request.headers['Authorization'], 'Bearer synthetic-key')
            return httpx.Response(200, json=PAYLOAD)
        api = AbstractEmail('synthetic-key', httpx.MockTransport(handler))
        try:
            summary = await api.lookup_email('person@example.com')
            self.assertEqual(summary.found, 3)
            self.assertNotIn('NEVER_DISPLAY', repr(summary))
        finally:
            await api.close()

    async def test_failures_are_sanitized(self):
        for response in [httpx.Response(401), httpx.Response(429), httpx.Response(500),
                         httpx.Response(200, text='invalid'), httpx.Response(200, json={}),
                         httpx.Response(200, json={'error': 'bad key'})]:
            api = AbstractEmail('synthetic-key', httpx.MockTransport(lambda request: response))
            try:
                with self.assertRaises(AbstractUnavailable) as caught:
                    await api.lookup_email('person@example.com')
                self.assertNotIn('person@example.com', str(caught.exception))
                self.assertNotIn('synthetic-key', str(caught.exception))
            finally:
                await api.close()

    async def test_timeout_and_missing_key(self):
        def timeout(request):
            raise httpx.ReadTimeout('private URL')
        for key in ('', 'synthetic-key'):
            api = AbstractEmail(key, httpx.MockTransport(timeout))
            try:
                with self.assertRaises(AbstractUnavailable):
                    await api.lookup_email('person@example.com')
            finally:
                await api.close()

    def test_report_dedup_counts_and_separate_assessments(self):
        summary = EmailSummary(BreachSummary(2, ('email',), (('example.com', '2020'),)), parse_summary(PAYLOAD))
        for report in (render_html('person@example.com', summary), render_txt('person@example.com', summary)):
            self.assertIn('LeakCheck', report)
            self.assertIn('AbstractAPI', report)
            self.assertIn('ریسک — AbstractAPI', report)
            self.assertIn('کیفیت — AbstractAPI', report)
            self.assertIn('قابلیت تحویل — AbstractAPI', report)
            self.assertIn('جمع نشده‌اند', report)
            self.assertEqual(report.casefold().count('• example.com'), 1)
            self.assertNotIn('NEVER_DISPLAY', report)
            self.assertNotIn('person@example.com', report)

class CombinedBillingTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.EmailBillingTests.setUp
    tearDown = fixtures.EmailBillingTests.tearDown
    balance = fixtures.EmailBillingTests.balance

    async def run_case(self, leak_failed=False, abstract_failed=False):
        abstract = SimpleNamespace(lookup_email=AsyncMock(return_value=parse_summary(PAYLOAD)))
        self.ctx.bot_data['abstract_email'] = abstract
        if leak_failed:
            self.api.lookup_email.side_effect = LeakCheckUnavailable('down')
        if abstract_failed:
            abstract.lookup_email.side_effect = AbstractUnavailable('down')
        await breach.breach_command(self.update, self.ctx)
        self.api.lookup_email.assert_awaited_once_with('person@example.com')
        abstract.lookup_email.assert_awaited_once_with('person@example.com')
        if leak_failed and abstract_failed:
            self.assertEqual(self.balance(), 1)
            self.assertEqual(self.files, [])
        else:
            self.assertEqual(self.balance(), 0)
            self.assertEqual(len(self.files), 1)
            self.assertIn('AbstractAPI', self.files[0][1])
            self.assertIn('LeakCheck', self.files[0][1])
            if leak_failed or abstract_failed:
                self.assertIn('در دسترس نیست', self.files[0][1])

    async def test_both_success_charge_once(self):
        await self.run_case()

    async def test_leakcheck_failure_preserves_abstract(self):
        await self.run_case(leak_failed=True)

    async def test_abstract_failure_preserves_leakcheck(self):
        await self.run_case(abstract_failed=True)

    async def test_both_fail_refunds(self):
        await self.run_case(leak_failed=True, abstract_failed=True)
