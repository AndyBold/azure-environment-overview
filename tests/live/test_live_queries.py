"""Read-only Azure checks. Opt in explicitly; never create fixtures or ingest data."""
import json
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.getenv('OVERVIEW_LIVE') == '1', 'Set OVERVIEW_LIVE=1 for read-only Azure validation')
class LiveQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from overview.azure import AzureClient
        cls.client = AzureClient()
        cls.config = json.loads(Path(os.environ['OVERVIEW_CONFIG']).read_text())

    def test_actual_inventory_query_and_subscription_access(self):
        from checker.collector import query
        for sub in self.config['subscriptions']:
            result = self.client.get_arm('/subscriptions/'+sub, '2022-12-01')
            self.assertEqual(result['tenantId'].lower(), self.config['tenantId'].lower())
        result = self.client.graph(query('inventory'), self.config['subscriptions'])
        self.assertEqual(len(result), len({r['id'].lower() for r in result}))
        self.assertTrue(all('type' in row and 'tags' in row for row in result))

    def test_actual_platform_group_and_alert_queries_compile(self):
        from checker.collector import query
        for name in ['resource-groups', 'platform-health', 'alerts']:
            with self.subTest(query=name):
                self.assertIsInstance(self.client.graph(query(name), self.config['subscriptions']), list)

    def test_snapshot_kql_executes_against_deployed_table(self):
        from workbook.build import build
        book = build(self.config)
        # Coverage query has no Workbook parameter expansions; execute its actual KQL.
        kql = next(i['content']['query'] for i in book['items'] if i['name']=='coverage')
        result = self.client.logs(self.config['workspaces'][0], kql)
        self.assertIsInstance(result, list)
        if result:
            self.assertEqual(result[0]['ExpectedCount'], result[0]['ActualCount'])

    def test_partial_ingestion_without_manifest_is_visible(self):
        from datetime import datetime, timedelta, timezone
        from workbook.build import build
        columns = json.loads(Path('infra/columns.json').read_text())
        now = datetime.now(timezone.utc)
        def fixture_row(kind, run, age, **extra):
            return {'RowKind': kind, 'RunId': run, 'ProjectId': self.config['projectId'],
                    'TimeGenerated': (now-timedelta(seconds=age)).isoformat(),
                    'SnapshotTime': (now-timedelta(seconds=age)).isoformat(), 'FreshnessSeconds': 300, **extra}
        rows = [fixture_row('resource', 'complete', 10, ResourceId='/a'),
                fixture_row('run', 'complete', 10, ExpectedCount=1, HealthComplete=True),
                fixture_row('resource', 'partial', 5, ResourceId='/a')]
        def literal(column, value):
            kind = column['type']
            if kind=='string': return json.dumps(value or '')
            if value is None: return {'boolean':'bool', 'datetime':'datetime', 'long':'long'}[kind]+'(null)'
            if kind=='datetime': return 'datetime('+value+')'
            if kind=='boolean': return 'true' if value else 'false'
            return str(value)
        definitions = ','.join(c['name']+':'+('bool' if c['type']=='boolean' else c['type']) for c in columns)
        values = ',\n'.join(','.join(literal(c, row.get(c['name'])) for c in columns) for row in rows)
        fixture = 'let fixture=datatable('+definitions+')['+values+'];\n'
        kql = next(i['content']['query'] for i in build(self.config)['items'] if i['name']=='coverage')
        result = self.client.logs(self.config['workspaces'][0], fixture+kql.replace('EnvironmentOverview_CL','fixture'))
        self.assertEqual(len(result), 1)
        self.assertIn('PARTIAL', result[0]['Coverage'])
