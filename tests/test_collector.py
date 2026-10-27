import importlib
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
RID = '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/api'
CONFIG = {'projectId': 'project', 'tenantId': 'tenant', 'subscriptions': ['sub'], 'workspaces': [],
          'endpoints': [{'resourceId': RID, 'checkId': 'health', 'url': 'https://api.internal/health'}]}


class FakeAzure:
    def __init__(self, health_error=False):
        self.health_error = health_error

    def get_arm(self, rid, api):
        return {'tenantId': 'tenant'}

    def graph(self, query, subscriptions):
        if query.startswith('ResourceContainers'):
            return [{'id': '/subscriptions/sub/resourceGroups/rg', 'name': 'rg',
                     'subscriptionId': 'sub', 'tags': {'Environment': 'dev'}}]
        if query.startswith('HealthResources'):
            if self.health_error:
                raise RuntimeError('unavailable')
            return [{'resourceId': RID.lower(), 'availabilityState': 'Available'}]
        if query.startswith('AlertsManagementResources'):
            return []
        return [{'id': RID, 'name': 'api', 'type': 'microsoft.app/containerapps', 'subscriptionId': 'sub',
                 'resourceGroup': 'rg', 'properties': {}},
                {'id': RID.replace('/api', '/shared'), 'name': 'shared', 'type': 'microsoft.app/containerapps',
                 'subscriptionId': 'sub', 'resourceGroup': 'rg', 'tags': {'env': 'shared'}, 'properties': {}}]

    def list_arm(self, rid, api):
        return []


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('checker/collector.py').exists(), 'collector missing')
        self.module = importlib.import_module('checker.collector')

    def run_collect(self, outcome='pass', client=None):
        def probe(target, **kw):
            return {'TimeGenerated': NOW.isoformat(), 'ResourceId': target['resourceId'].lower(),
                    'CheckId': target['checkId'], 'Outcome': outcome, 'HttpStatus': 200 if outcome=='pass' else 503,
                    'DurationMs': 1, 'Reason': 'test', 'Revision': ''}
        return self.module.collect(CONFIG, client or FakeAzure(), probe_fn=probe, now=NOW)

    def test_pipeline_discovers_attribution_and_combines_signals(self):
        rows, manifest = self.run_collect()
        api = next(r for r in rows if r['RowKind']=='resource' and r['Name']=='api')
        self.assertEqual((api['Environment'], api['Status']), ('dev', 'green'))
        shared = next(r for r in rows if r['RowKind']=='resource' and r['Name']=='shared')
        self.assertEqual((shared['Classification'], shared['Status']), ('shared', 'grey'))
        self.assertEqual(manifest['ExpectedCount'], 2)
        self.assertTrue(manifest['HealthComplete'])

    def test_health_query_failure_retains_inventory_and_endpoint_failure(self):
        rows, manifest = self.run_collect('fail', FakeAzure(health_error=True))
        resources = [r for r in rows if r['RowKind']=='resource']
        self.assertEqual(len(resources), 2)
        api = next(r for r in resources if r['Name']=='api')
        self.assertEqual((api['Status'], api['PlatformStatus']), ('red', 'grey'))
        self.assertIn('platform', manifest['CollectionIssues'])

    def test_wrong_tenant_is_rejected(self):
        config = deepcopy(CONFIG)
        config['tenantId'] = 'different'
        with self.assertRaises(ValueError):
            self.module.collect(config, FakeAzure(), now=NOW)

    def test_invalid_endpoint_targets_and_duplicate_ids_rejected(self):
        config = deepcopy(CONFIG)
        config['endpoints'][0]['url'] = 'https://user:secret@api/health'
        with self.assertRaises(ValueError):
            self.module.collect(config, FakeAzure(), now=NOW)
        config = deepcopy(CONFIG)
        other = deepcopy(config['endpoints'][0]); other['url'] = 'https://different/health'
        config['endpoints'].append(other)
        with self.assertRaises(ValueError):
            self.module.collect(config, FakeAzure(), now=NOW)
