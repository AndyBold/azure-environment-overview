"""Cases found by independent review and author data-flow tracing."""
import unittest
from datetime import datetime, timedelta, timezone
from tests.test_collector import CONFIG, RID, FakeAzure
from checker.collector import collect
from checker.discovery import targets_for
from workbook.build import build

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


class ReviewRegressions(unittest.TestCase):
    def test_fresh_failed_check_keeps_its_own_evidence_time(self):
        source = {'workspaceResourceId': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w',
                  'query': 'q', 'checks': [{'resourceId': RID, 'checkId': 'fresh'}, {'resourceId': RID, 'checkId': 'old'}]}
        client = FakeAzure()
        client.logs = lambda *args: [
            {'ResourceId': RID, 'CheckId': 'fresh', 'Outcome': 'fail', 'TimeGenerated': NOW.isoformat(), 'Reason': 'HTTP 503'},
            {'ResourceId': RID, 'CheckId': 'old', 'Outcome': 'pass', 'TimeGenerated': (NOW-timedelta(minutes=10)).isoformat(), 'Reason': 'old'}]
        rows, _ = collect({**CONFIG, 'endpoints': [], 'existingEndpointQueries': [source]}, client, now=NOW)
        api = next(r for r in rows if r.get('Name')=='api')
        self.assertEqual(api['Status'], 'red')
        self.assertEqual(api['ApplicationEvidenceAt'], NOW.isoformat())

    def test_selection_parameter_declared_before_summary_and_not_redeclared(self):
        workbook = build(CONFIG)
        definitions = [(index, p) for index, item in enumerate(workbook['items']) if item['type']==9
                       for p in item['content']['parameters'] if p['name']=='SelectedEnvironment']
        summary_index = next(index for index, item in enumerate(workbook['items']) if item['name']=='environment-summary')
        self.assertEqual(len(definitions), 1)
        self.assertLess(definitions[0][0], summary_index)
        self.assertTrue(definitions[0][1].get('isGlobal'))

    def test_inactive_revision_endpoint_override_is_ignored(self):
        resource = {'id': RID, 'type': 'microsoft.app/containerapps', 'properties': {
            'latestRevisionName': 'api--new', 'configuration': {'ingress': {'traffic': [
                {'revisionName': 'api--new', 'weight': 100}, {'revisionName': 'api--old', 'weight': 0}]}}}}
        endpoints = [{'resourceId': RID, 'checkId': 'new', 'revision': 'api--new', 'url': 'https://new/health'},
                     {'resourceId': RID, 'checkId': 'old', 'revision': 'api--old', 'url': 'https://old/health'}]
        targets, _ = targets_for([resource], {'endpoints': endpoints})
        self.assertEqual([t['checkId'] for t in targets], ['new'])

    def test_mixed_case_parent_override_is_honoured(self):
        client = FakeAzure()
        original = client.graph
        def graph(query, subs):
            rows = original(query, subs)
            if query.startswith('Resources\n'):
                rows.append({'id': '/subscriptions/sub/resourceGroups/rg/providers/X/y/parent',
                             'name': 'parent', 'type': 'X/y', 'subscriptionId': 'sub', 'resourceGroup': 'rg', 'tags': {'env': 'uat'}})
            return rows
        client.graph = graph
        cfg = {**CONFIG, 'endpoints': [], 'parentOverrides': {RID: '/subscriptions/sub/resourceGroups/rg/providers/X/y/parent'}}
        rows, _ = collect(cfg, client, now=NOW)
        self.assertEqual(next(r for r in rows if r.get('Name')=='api')['Environment'], 'uat')

    def test_missing_group_evidence_blocks_confident_name_fallback(self):
        client = FakeAzure()
        original = client.graph
        def graph(query, subs):
            if query.startswith('ResourceContainers'):
                raise RuntimeError('group access failed')
            return original(query, subs)
        client.graph = graph
        cfg = {**CONFIG, 'endpoints': [], 'namingRules': [{'token': 'api', 'environment': 'dev'}]}
        rows, _ = collect(cfg, client, now=NOW)
        api = next(r for r in rows if r.get('Name')=='api')
        self.assertEqual(api['Classification'], 'unassigned')
        self.assertIn('unavailable', api['AttributionIssues'])

    def test_latest_sample_wins_across_existing_telemetry_sources(self):
        source = {'workspaceResourceId': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w',
                  'checks': [{'resourceId': RID, 'checkId': 'ready'}]}
        cfg = {**CONFIG, 'endpoints': [], 'existingEndpointQueries': [{**source, 'query': 'old'}, {**source, 'query': 'new'}]}
        client = FakeAzure()
        client.logs = lambda workspace, query: [{'ResourceId': RID, 'CheckId': 'ready',
            'Outcome': 'fail' if query=='old' else 'pass', 'TimeGenerated': (NOW-timedelta(seconds=60) if query=='old' else NOW).isoformat(), 'Reason': query}]
        rows, _ = collect(cfg, client, now=NOW)
        self.assertEqual(next(r for r in rows if r.get('Name')=='api')['Status'], 'green')
        self.assertEqual(len([r for r in rows if r['RowKind']=='endpoint']), 1)

    def test_inferred_probe_does_not_apply_latest_template_to_old_serving_revision(self):
        resource = {'id': RID, 'type': 'microsoft.app/containerapps', 'properties': {
            'latestRevisionName': 'api--new', 'configuration': {'ingress': {'fqdn': 'api.internal', 'targetPort': 8080,
                'traffic': [{'revisionName': 'api--old', 'weight': 100}]}},
            'template': {'containers': [{'name': 'api', 'probes': [{'type': 'Readiness', 'httpGet': {'path': '/newready', 'port': 8080}}]}]}}}
        targets, issues = targets_for([resource], {'discoverReadinessProbes': True})
        self.assertEqual(targets, [])
        self.assertIn(RID.lower(), issues)

    def test_deallocated_vm_is_unknown_instead_of_red(self):
        client = FakeAzure()
        original = client.graph
        vmid = '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm'
        def graph(query, subs):
            rows = original(query, subs)
            if query.startswith('Resources\n'):
                rows.append({'id': vmid, 'name': 'vm', 'type': 'microsoft.compute/virtualmachines',
                    'subscriptionId': 'sub', 'resourceGroup': 'rg', 'tags': {'env': 'dev'},
                    'properties': {'extended': {'instanceView': {'powerState': {'code': 'PowerState/deallocated'}}}}})
            elif query.startswith('HealthResources'):
                rows.append({'resourceId': vmid, 'availabilityState': 'Unavailable'})
            return rows
        client.graph = graph
        rows, _ = collect({**CONFIG, 'endpoints': []}, client, now=NOW)
        self.assertEqual(next(r for r in rows if r.get('Name')=='vm')['Status'], 'grey')

    def test_conflicting_parent_override_key_casing_is_rejected(self):
        cfg = {**CONFIG, 'parentOverrides': {RID: '/parent/a', RID.lower(): '/parent/b'}}
        with self.assertRaises(ValueError):
            collect(cfg, FakeAzure(), now=NOW)

    def test_proven_inactive_telemetry_check_does_not_create_missing_check(self):
        source = {'workspaceResourceId': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w',
                  'query': 'q', 'checks': [{'resourceId': RID, 'checkId': 'old'}, {'resourceId': RID, 'checkId': 'new'}]}
        client = FakeAzure()
        original = client.graph
        def graph(query, subs):
            rows = original(query, subs)
            if query.startswith('Resources\n'):
                rows[0]['properties'] = {'configuration': {'ingress': {'traffic': [{'revisionName': 'new', 'weight': 100}]}}}
            return rows
        client.graph = graph
        client.logs = lambda *args: [{'ResourceId': RID, 'CheckId': revision, 'Revision': revision,
            'Outcome': 'fail' if revision=='old' else 'pass', 'TimeGenerated': NOW.isoformat(), 'Reason': revision}
            for revision in ('old', 'new')]
        rows, _ = collect({**CONFIG, 'endpoints': [], 'existingEndpointQueries': [source]}, client, now=NOW)
        self.assertEqual(next(r for r in rows if r.get('Name')=='api')['Status'], 'green')

    def test_multi_revision_application_health_requires_each_serving_revision(self):
        client = FakeAzure()
        original = client.graph
        def graph(query, subs):
            rows = original(query, subs)
            if query.startswith('Resources\n'):
                rows[0]['properties'] = {'configuration': {'ingress': {'traffic': [
                    {'revisionName': 'a', 'weight': 50}, {'revisionName': 'b', 'weight': 50}]}}}
            return rows
        client.graph = graph
        source = {'workspaceResourceId': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w',
                  'query': 'q', 'checks': [{'resourceId': RID, 'checkId': 'ready-a'}]}
        client.logs = lambda *args: [{'ResourceId': RID, 'CheckId': 'ready-a', 'Revision': 'a',
            'Outcome': 'pass', 'TimeGenerated': NOW.isoformat(), 'Reason': 'a healthy'}]
        rows, _ = collect({**CONFIG, 'endpoints': [], 'existingEndpointQueries': [source]}, client, now=NOW)
        api = next(r for r in rows if r.get('Name')=='api')
        self.assertEqual(api['ApplicationStatus'], 'grey')
        self.assertIn('b', api['Reason'])
