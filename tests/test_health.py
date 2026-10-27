import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('overview/health.py').exists(), 'health implementation missing')
        self.health = importlib.import_module('overview.health')

    def test_alert_severity_and_positive_evidence(self):
        for severity, expected in [('Sev0', 'red'), ('Sev1', 'red'), ('Sev2', 'amber'),
                                   ('Sev3', 'amber'), ('Sev4', 'grey')]:
            with self.subTest(severity=severity):
                result = self.health.evaluate(None, [{'severity': severity}], [], NOW)
                self.assertEqual(result['status'], expected)
        self.assertEqual(self.health.evaluate({'availabilityState': 'Available'}, [], [], NOW)['status'], 'green')
        self.assertEqual(self.health.evaluate(None, [], [], NOW)['status'], 'grey')

    def test_missing_required_signal_does_not_earn_green(self):
        result = self.health.evaluate({'availabilityState': 'Available'}, [], [], NOW, application_required=True)
        self.assertEqual(result['status'], 'grey')
        self.assertEqual(result['applicationStatus'], 'grey')

    def test_stale_endpoints_and_failures(self):
        for outcome, age, expected in [('pass', 0, 'green'), ('fail', 0, 'red'),
                                        ('pass', 301, 'grey'), ('fail', 301, 'grey')]:
            obs = [{'Outcome': outcome, 'TimeGenerated': (NOW-timedelta(seconds=age)).isoformat(), 'Reason': 'test'}]
            self.assertEqual(self.health.evaluate({'availabilityState': 'Available'}, [], obs, NOW,
                                                 application_required=True)['status'], expected)

    def test_unknown_platform_preserves_known_application_failure(self):
        obs = [{'Outcome': 'fail', 'TimeGenerated': NOW.isoformat(), 'Reason': 'HTTP 503'}]
        result = self.health.evaluate(None, [], obs, NOW, application_required=True)
        self.assertEqual(result['status'], 'red')
        self.assertEqual(result['platformStatus'], 'grey')

    def test_all_equal_rollup_and_empty_unknown(self):
        for statuses, expected in [([], 'grey'), (['green', 'grey'], 'grey'),
                                   (['grey', 'amber'], 'amber'), (['amber', 'red'], 'red')]:
            self.assertEqual(self.health.worst(statuses), expected)

    def test_stopped_resource_is_unknown(self):
        result = self.health.evaluate({'availabilityState': 'Unavailable', 'intentionalStop': True}, [], [], NOW)
        self.assertEqual(result['status'], 'grey')
