"""A report must preserve technical facts without inventing legal approval."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

from dejavu.core import Disk, Inventory, JobResult
from dejavu.engine import run_batch
from dejavu.reports import save_disk_record, save_reports
from dejavu.simulation import FileSession


class ReportFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.disk = Disk(1, 'Disco <prova>', 'SERIALE<&>', 'ID-1', 65536, 512,
                         'SATA', 'HDD', simulated=True)

    def test_success_failure_and_block_never_create_legal_or_human_approval(self):
        for status in ('SUCCESS', 'FAILED', 'BLOCKED', 'CANCELLED'):
            with self.subTest(status=status):
                result = JobResult(self.disk, status, 'Esito di prova')
                path = save_disk_record(self.root, result, 'lotto-' + status)
                payload = json.loads(path.read_text())
                self.assertEqual(payload['result']['status'], status)
                doc = payload['documentation']
                self.assertFalse(doc['gdpr_certified'])
                self.assertFalse(doc['purge_certified'])
                self.assertEqual(doc['human_validation']['status'], 'NOT_RECORDED')
                self.assertIsNone(doc['operator'])
                self.assertIsNone(doc['assignment_reference'])
                self.assertEqual(doc['qualified_signature'], 'NOT_APPLIED')
                self.assertEqual(doc['qualified_timestamp'], 'NOT_APPLIED')

    def test_printable_report_links_exact_original_json_with_hash_and_limitations(self):
        result = JobResult(self.disk, 'SUCCESS', '<esito>', self.disk.size, self.disk.size)
        html, data = save_reports(self.root, Inventory((self.disk,), True, simulated=True),
                                  [result], 2, batch_id='lotto-123')
        text = html.read_text()
        payload = json.loads(data.read_text())
        self.assertIn(hashlib.sha256(data.read_bytes()).hexdigest(), text)
        self.assertIn(data.name, text)
        self.assertEqual(payload['batch_id'], 'lotto-123')
        self.assertEqual(payload['documentation']['document_id'], 'lotto-123')
        self.assertIn('SIMULAZIONE', text)
        self.assertNotIn('<esito>', text)
        self.assertIn('&lt;esito&gt;', text)
        self.assertIn('non prova', text)
        self.assertIn('non sono attestazioni', text)
        self.assertIn('non acquisita', text)
        self.assertEqual({r['id'] for r in payload['documentation']['references']},
                         {'GDPR', 'GPDP-2008-1571514', 'NIST-SP-800-88R2'})

    def test_native_ssd_success_keeps_native_evidence_without_purge_certification(self):
        disk = replace(self.disk, kind='SSD')
        result = JobResult(disk, 'SUCCESS', 'Esito nativo')
        result.native_details = {'completion': 'device_confirmed'}
        html, data = save_reports(self.root, Inventory((disk,), True, simulated=True), [result], 1)
        payload = json.loads(data.read_text())
        self.assertIsNone(payload['results'][0]['written'])
        self.assertIsNone(payload['results'][0]['verified'])
        self.assertFalse(payload['documentation']['purge_certified'])
        self.assertIn('ESITO DEL DISPOSITIVO CONFERMATO', html.read_text())

    def test_complete_batch_and_progressive_record_have_the_same_traceable_identifier(self):
        disk = self.disk
        file = self.root / 'only-owned-simulation.bin'
        file.write_bytes(b'x' * disk.size)
        inventory = Inventory((disk,), True, simulated=True)
        class Backend:
            def scan(self):
                return inventory
            def open_session(self, target):
                return FileSession(file)
        events = []
        results, paths = run_batch((disk,), inventory, Backend(), Event(), events.append,
                                   self.root / 'rapporti', 1)
        final = json.loads(paths[1].read_text())
        record = json.loads(events[-1]['disk_records'][0].read_text())
        batch = events[-1]['batch_id']
        self.assertEqual(results[0].status, 'SUCCESS')
        self.assertEqual(final['batch_id'], batch)
        self.assertEqual(record['batch_id'], batch)
        self.assertEqual(record['documentation']['document_id'], batch + '-Disco-001')

    def test_untrusted_identifier_cannot_escape_report_folder(self):
        result = JobResult(self.disk, 'BLOCKED', 'Test')
        for value in ('../escape', 'a/b', 'C:\\escape', 'invalid.name', ''):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    save_disk_record(self.root, result, value)
                if value:
                    with self.assertRaises(ValueError):
                        save_reports(self.root, Inventory((self.disk,), True), [result], 1, batch_id=value)


if __name__ == '__main__':
    unittest.main()
