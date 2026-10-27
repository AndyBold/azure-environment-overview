import importlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.test_collector import CONFIG


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('workbook/build.py').exists(), 'Workbook generator missing')
        self.build = importlib.import_module('workbook.build')

    def test_generated_workbook_has_live_and_health_views(self):
        workbook = self.build.build(CONFIG)
        self.assertEqual(workbook['version'], 'Notebook/1.0')
        names = {item['name'] for item in workbook['items']}
        self.assertTrue({'environment-summary', 'resources', 'shared', 'unassigned', 'live-inventory', 'coverage'} <= names)
        queries = [i['content'] for i in workbook['items'] if i['type']==3]
        self.assertTrue(any(q.get('queryType')==1 for q in queries))
        self.assertTrue(any(q.get('queryType')==0 for q in queries))
        self.assertNotIn('https://api.internal', json.dumps(workbook))

    def test_generator_rejects_query_injection_and_writes_json(self):
        with self.assertRaises(ValueError):
            self.build.build({**CONFIG, 'projectId': "x'; drop table x"})
        with tempfile.TemporaryDirectory() as tmp:
            cfg, dest = Path(tmp)/'config.json', Path(tmp)/'workbook.json'
            cfg.write_text(json.dumps(CONFIG))
            subprocess.run(['python', '-m', 'workbook.build', '--config', str(cfg), '--output', str(dest)], check=True)
            self.assertEqual(json.loads(dest.read_text())['version'], 'Notebook/1.0')

    def test_resource_rows_match_ingestion_schema(self):
        from checker.collector import collect
        from tests.test_collector import FakeAzure
        rows, manifest = collect({**CONFIG, 'endpoints': []}, FakeAzure())
        columns = {c['name']: c['type'] for c in json.loads(Path('infra/columns.json').read_text())}
        for row in [*rows, manifest]:
            self.assertFalse(set(row)-set(columns), 'collector emitted fields absent from DCR')
            for name, value in row.items():
                if value is None: continue
                kind = columns[name]
                if kind=='string': self.assertIsInstance(value, str)
                elif kind=='boolean': self.assertIsInstance(value, bool)
                elif kind=='long': self.assertIsInstance(value, int)

    @unittest.skipUnless(shutil.which('az') or shutil.which('bicep'), 'Azure CLI/Bicep not installed')
    def test_bicep_compiles(self):
        command = ['az', 'bicep', 'build'] if shutil.which('az') else ['bicep', 'build']
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([*command, '--file', 'infra/main.bicep', '--outfile', tmp+'/main.json'], check=True)
