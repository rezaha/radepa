"""Optional configuration remains disabled without installing Sherlock."""
import os
import unittest
from unittest.mock import patch


class SherlockConfigTests(unittest.TestCase):
    def settings(self, **overrides):
        env = {'BOT_TOKEN':'123456:offline', 'ADMIN_IDS':'999',
               'PAYMENT_CARD_NUMBER':'test', 'PAYMENT_CARD_HOLDER':'test',
               'SERPER_API_KEY':'test', **overrides}
        with patch.dict(os.environ, env, clear=True):
            from app.config import Config
            return Config.from_env()

    def test_default_disabled_and_resource_limits(self):
        config = self.settings()
        self.assertFalse(config.sherlock_enabled)
        self.assertEqual(config.sherlock_binary, 'sherlock')
        self.assertEqual((config.sherlock_max_concurrent, config.sherlock_site_timeout,
                          config.sherlock_total_timeout, config.sherlock_cooldown), (1, 10, 120, 60))

    def test_explicit_opt_in_and_binary_path(self):
        config = self.settings(SHERLOCK_ENABLED='true', SHERLOCK_BINARY='/test tool/bin/sherlock',
                               SHERLOCK_MAX_CONCURRENT='2', SHERLOCK_SITE_TIMEOUT='5',
                               SHERLOCK_TOTAL_TIMEOUT='90', SHERLOCK_COOLDOWN='120')
        self.assertTrue(config.sherlock_enabled)
        self.assertEqual(config.sherlock_binary, '/test tool/bin/sherlock')
        self.assertEqual((config.sherlock_max_concurrent, config.sherlock_site_timeout,
                          config.sherlock_total_timeout, config.sherlock_cooldown), (2, 5, 90, 120))
