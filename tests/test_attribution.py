import unittest
from pathlib import Path
import importlib


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('overview/attribution.py').exists(), 'attribution implementation missing')
        self.module = importlib.import_module('overview.attribution')

    def resolve(self, tags, **kw):
        return self.module.attribute({'id': '/subscriptions/s/resourceGroups/rg/providers/X/y/item',
                                      'name': kw.pop('name', 'item'), 'tags': tags}, **kw)

    def test_case_alias_and_normalisation(self):
        result = self.resolve({'eNvIrOnMeNt': ' DEV '})
        self.assertEqual((result['environment'], result['classification']), ('dev', 'nonproduction'))
        self.assertEqual(result['originalEnvironment'], ' DEV ')

    def test_conflicting_aliases_are_unassigned(self):
        result = self.resolve({'Environment': 'dev', 'env': 'test'})
        self.assertEqual(result['classification'], 'unassigned')
        self.assertIn('conflict', result['attributionIssues'].lower())

    def test_direct_tag_wins_but_discrepancy_visible(self):
        result = self.resolve({'Environment': 'test'}, group_tags={'Environment': 'dev'})
        self.assertEqual(result['environment'], 'test')
        self.assertIn('disagree', result['attributionIssues'])

    def test_parent_before_group_and_shared_distinct(self):
        result = self.resolve({}, parent_tags={'env': 'shared'}, group_tags={'env': 'dev'})
        self.assertEqual((result['environment'], result['classification']), ('shared', 'shared'))
        self.assertIn('missing direct', result['attributionIssues'])

    def test_unfamiliar_labels_are_visible_unclassified(self):
        result = self.resolve({'Environment': 'blue'})
        self.assertEqual((result['environment'], result['classification']), ('blue', 'unclassified'))
        self.assertEqual(self.resolve({})['classification'], 'unassigned')

    def test_name_rules_require_tokens_and_ambiguity_is_unknown(self):
        config = {'namingRules': [{'token': 'dev', 'environment': 'dev'},
                                  {'token': 'test', 'environment': 'test'}]}
        self.assertEqual(self.resolve({}, name='dev-api', config=config)['environment'], 'dev')
        self.assertEqual(self.resolve({}, name='device', config=config)['classification'], 'unassigned')
        self.assertEqual(self.resolve({}, name='dev-test-api', config=config)['classification'], 'unassigned')

    def test_classification_and_resource_overrides(self):
        self.assertEqual(self.resolve({'env': 'prod'})['classification'], 'production')
        self.assertEqual(self.resolve({'env': 'blue'}, config={'classificationOverrides': {'blue': 'production'}})['classification'], 'production')
        rid = '/subscriptions/s/resourcegroups/rg/providers/x/y/item'
        result = self.resolve({'env': 'dev', 'Environment': 'test'}, config={'resourceOverrides': {rid: 'uat'}})
        self.assertEqual(result['environment'], 'uat')


if __name__ == '__main__':
    unittest.main()
