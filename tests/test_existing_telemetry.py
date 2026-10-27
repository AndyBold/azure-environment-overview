import unittest
from datetime import datetime, timezone
from tests.test_collector import CONFIG, RID, FakeAzure
from checker.collector import collect
from overview.azure import AzureClient


class ExistingTelemetryTests(unittest.TestCase):
    def test_existing_monitor_samples_can_replace_http_checker(self):
        config = {**CONFIG, 'endpoints': [], 'existingEndpointQueries': [{
            'workspaceResourceId': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/logs',
            'query': 'existing query', 'checks': [{'resourceId': RID, 'checkId': 'ready'}]}]}
        client = FakeAzure()
        now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        client.logs = lambda *args: [{'ResourceId': RID, 'CheckId': 'ready', 'Outcome': 'pass',
                                      'TimeGenerated': now.isoformat(), 'Reason': 'Existing health monitor'}]
        rows, _ = collect(config, client, now=now)
        row = next(r for r in rows if r['RowKind']=='resource' and r['Name']=='api')
        self.assertEqual(row['Status'], 'green')
        client.logs = lambda *args: []
        rows, _ = collect(config, client, now=now)
        row = next(r for r in rows if r['RowKind']=='resource' and r['Name']=='api')
        self.assertEqual(row['Status'], 'grey')

    def test_azure_logs_table_mapping_and_partial_error(self):
        responses = iter([{'properties': {'customerId': 'workspace-guid'}},
                          {'tables': [{'columns': [{'name': 'ResourceId'}, {'name': 'Outcome'}],
                                       'rows': [[RID, 'pass']]}]}])
        client = AzureClient(lambda *args: next(responses))
        self.assertTrue(hasattr(client, 'logs'), 'Log Analytics integration missing')
        self.assertEqual(client.logs('/workspaces/test', 'query'), [{'ResourceId': RID, 'Outcome': 'pass'}])
        client = AzureClient(lambda method, *args: {'properties': {'customerId': 'guid'}} if method=='GET' else
                             {'error': {'code': 'PartialError'}, 'tables': []})
        with self.assertRaises(RuntimeError):
            client.logs('/workspaces/test', 'query')
