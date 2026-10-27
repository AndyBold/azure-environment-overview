import importlib
import unittest
import urllib.error
import socket
from pathlib import Path
from datetime import datetime, timezone

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
RID = '/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/api'


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('checker/probes.py').exists(), 'checker implementation missing')
        self.probes = importlib.import_module('checker.probes')
        self.discovery = importlib.import_module('checker.discovery')

    def target(self, **kw):
        return {'resourceId': RID, 'checkId': 'ready', 'url': 'https://api.internal/health', **kw}

    def test_http_success_and_failure(self):
        for code, outcome in [(200, 'pass'), (204, 'pass'), (302, 'fail'), (503, 'fail'), (401, 'unknown')]:
            result = self.probes.probe(self.target(), transport=lambda *a: code, now=NOW)
            self.assertEqual((result['Outcome'], result['HttpStatus']), (outcome, code))
            self.assertEqual(result['ResourceId'], RID.lower())

    def test_network_errors_classified_without_leaking_secrets(self):
        def failing(exc):
            def transport(*args):
                raise exc
            return transport
        for exc, expected in [(socket.timeout('secret'), 'fail'),
                              (urllib.error.URLError(socket.gaierror('secret')), 'unknown')]:
            result = self.probes.probe(self.target(), transport=failing(exc), now=NOW)
            self.assertEqual(result['Outcome'], expected)
            self.assertNotIn('secret', str(result))

    def test_no_application_targets_without_configuration(self):
        rows = [{'id': RID, 'type': 'microsoft.app/containerapps', 'properties': {}}]
        targets, issues = self.discovery.targets_for(rows, {})
        self.assertEqual(targets, [])

    def test_readiness_probe_respects_routable_port_and_path(self):
        row = {'id': RID, 'type': 'microsoft.app/containerapps', 'properties': {
            'configuration': {'ingress': {'fqdn': 'api.internal', 'targetPort': 8080}},
            'template': {'containers': [{'name': 'api', 'probes': [{'type': 'Readiness',
                            'httpGet': {'path': '/ready', 'port': 8080}}]}]}}}
        targets, issues = self.discovery.targets_for([row], {'discoverReadinessProbes': True})
        self.assertEqual(targets[0]['url'], 'https://api.internal/ready')
        row['properties']['template']['containers'][0]['probes'][0]['httpGet']['port'] = 9090
        targets, issues = self.discovery.targets_for([row], {'discoverReadinessProbes': True})
        self.assertEqual(targets, [])
        self.assertTrue(issues[RID.lower()])

    def test_override_replaces_discovered_probe_and_deduplicates(self):
        override = self.target()
        targets, _ = self.discovery.targets_for([{'id': RID, 'type': 'microsoft.app/containerapps'}],
                                                {'endpoints': [override, dict(override)]})
        self.assertEqual(len(targets), 1)

    def test_managed_identity_header_not_in_result(self):
        seen = []
        target = self.target(tokenScope='api://private/.default')
        result = self.probes.probe(target, transport=lambda url, headers, timeout: seen.append(headers) or 200,
                                   token_provider=lambda scope: 'secret-token', now=NOW)
        self.assertEqual(seen[0]['Authorization'], 'Bearer secret-token')
        self.assertNotIn('secret-token', str(result))
