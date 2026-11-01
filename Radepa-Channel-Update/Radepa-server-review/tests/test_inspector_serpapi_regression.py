"""The new inspector must not remove the existing paid SerpAPI analysis path."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import test_single_search_payments as fixtures
from app.services.job_service import JobService
from app.db.repos import UserRepo

class SerpAPIRegressionTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.InstagramBillingTests.setUp
    tearDown=fixtures.InstagramBillingTests.tearDown

    async def test_serpapi_result_is_merged_and_only_instagram_credit_consumed(self):
        source={'link':'https://example.com/public-result','title':'Public result','source':'serpapi'}
        self.service._serpapi=SimpleNamespace(analyze=AsyncMock(return_value=[source]))
        result=await self.service.run_analysis(123,'example_user')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['sources'],[source])
        self.service._serpapi.analyze.assert_awaited_once_with('example_user')
        account=UserRepo.get_by_telegram_id(123)
        self.assertEqual(account['instagram_credits'],0)
        self.assertEqual(account['email_credits'],2)
