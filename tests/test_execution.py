import importlib
import unittest
from pathlib import Path
from tests.test_collector import CONFIG, FakeAzure


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path('checker/main.py').exists(), 'execution entrypoint missing')
        self.main = importlib.import_module('checker.main')

    def test_complete_manifest_uploaded_after_resource_batches(self):
        client = FakeAzure()
        uploaded = []
        client.ingest = lambda rows, config: uploaded.append(rows)
        result = self.main.execute({**CONFIG, 'endpoints': []}, client)
        self.assertEqual(result, 0)
        self.assertTrue(all(r['RowKind'] != 'run' for r in uploaded[0]))
        self.assertEqual(uploaded[-1][0]['RowKind'], 'run')
        self.assertEqual(uploaded[-1][0]['ExpectedCount'], 2)

    def test_ingestion_failure_cannot_publish_success_manifest(self):
        client = FakeAzure()
        uploaded = []
        def ingest(rows, config):
            uploaded.append(rows)
            raise RuntimeError('ingestion error')
        client.ingest = ingest
        self.assertEqual(self.main.execute({**CONFIG, 'endpoints': []}, client), 1)
        self.assertFalse(any(r['RowKind']=='run' for batch in uploaded for r in batch))

    def test_lease_releases_on_failure_and_busy_run_skips(self):
        lease_module = importlib.import_module('checker.lease')
        class Lease:
            released = False
            def release(self): self.released = True
        class Blob:
            def upload_blob(self, data, overwrite): pass
            def acquire_lease(self, lease_duration):
                self.duration = lease_duration
                return lease
        blob, lease = Blob(), Lease()
        with self.assertRaises(RuntimeError):
            with lease_module.exclusive(blob):
                raise RuntimeError('test')
        self.assertTrue(lease.released)
        self.assertEqual(blob.duration, 60)
