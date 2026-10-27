import importlib
import unittest
from pathlib import Path


class AzureTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('overview/azure.py').exists(), 'Azure client implementation missing')
        self.azure = importlib.import_module('overview.azure')

    def test_all_graph_pages_are_returned_and_scope_preserved(self):
        requests = []
        def transport(method, url, payload, scope):
            requests.append(payload)
            if payload['options'].get('$skipToken') == 'page2':
                return {'data': [{'id': '/b'}], 'resultTruncated': 'false'}
            return {'data': [{'id': '/a'}], '$skipToken': 'page2', 'resultTruncated': 'true'}
        result = self.azure.AzureClient(transport).graph('Resources | project id', ['sub'])
        self.assertEqual([r['id'] for r in result], ['/a', '/b'])
        self.assertEqual(requests[1]['subscriptions'], ['sub'])
        self.assertEqual(requests[1]['options']['$skipToken'], 'page2')

    def test_truncation_without_token_and_repeated_tokens_fail(self):
        for response in [{'data': [], 'resultTruncated': 'true'},
                         {'data': [], '$skipToken': 'same', 'resultTruncated': 'true'}]:
            with self.assertRaises(self.azure.CoverageError):
                self.azure.AzureClient(lambda *args: response).graph('Resources', ['sub'])

    def test_ingestion_batches_and_rejects_oversized_rows(self):
        calls = []
        client = self.azure.AzureClient(lambda *args: calls.append(args) or {})
        client.ingest([{'x': 'a'*500}, {'x': 'b'*500}], {'endpoint': 'https://test.ingest.monitor.azure.com',
                      'ruleId': 'dcr-test', 'stream': 'Custom-EnvironmentOverview'}, max_bytes=800)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], 'POST')
        self.assertEqual(calls[0][3], 'https://monitor.azure.com/.default')
        with self.assertRaises(ValueError):
            client.ingest([{'x': 'a'*900}], {'endpoint': 'https://test', 'ruleId': 'x', 'stream': 'x'}, max_bytes=800)
