"""Progressive records survive a still-running batch; file APIs only."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from dejavu.core import Disk, Inventory
from dejavu.engine import run_batch
from dejavu.reports import save_disk_record
from dejavu.simulation import FileSession


class BatchRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.disk = Disk(1, "HDD di prova", "DEMO-1", "id1", 65536, 512,
                         "SATA", "HDD", simulated=True)

    def test_record_is_on_disk_while_another_drive_is_still_verifying(self):
        first = self.disk
        second = replace(first, number=2, serial="DEMO-2", unique_id="id2")
        targets = (first, second)
        inventory = Inventory(targets, True, simulated=True)
        files = {}
        for d in targets:
            files[d.number] = self.root / f"target-{d.number}.bin"
            files[d.number].write_bytes(b'\xA5' * d.size)
        waiting, release, saved = Event(), Event(), Event()
        records, events, output = [], [], []
        class PausedSession(FileSession):
            def rewind(self):
                super().rewind()
                waiting.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the paused reader")
        class Backend:
            def scan(self):
                return inventory
            def open_session(self, d):
                return (PausedSession if d.number == 2 else FileSession)(files[d.number])
        def persist(folder, result, batch_id):
            path = save_disk_record(folder, result, batch_id)
            records.append(path)
            if result.disk.number == 1:
                saved.set()
            return path
        with patch("dejavu.engine.save_disk_record", side_effect=persist):
            thread = Thread(target=lambda: output.append(run_batch(targets, inventory, Backend(),
                Event(), events.append, self.root / 'reports', 2)))
            thread.start()
            try:
                self.assertTrue(waiting.wait(2))
                self.assertTrue(saved.wait(2))
                self.assertTrue(thread.is_alive())
                payload = json.loads(records[0].read_text())
                self.assertEqual(payload['result']['status'], 'SUCCESS')
                self.assertEqual(payload['result']['verified'], first.size)
                self.assertEqual(len(list((self.root/'reports').rglob('Disco-*.json'))), 1)
                self.assertFalse(any(e['type']=='batch_done' for e in events))
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(records), 2)
        self.assertEqual({r.status for r in output[0][0]}, {'SUCCESS'})
        self.assertEqual(len(json.loads(output[0][1][1].read_text())['results']), 2)

    def test_record_failure_does_not_change_erasure_or_lose_final_report(self):
        disk = self.disk
        inventory = Inventory((disk,), True, simulated=True)
        path = self.root/'target.bin'; path.write_bytes(b'\xA5'*disk.size)
        events = []
        class Backend:
            def scan(self):
                return inventory
            def open_session(self, d):
                return FileSession(path)
        with patch("dejavu.engine.save_disk_record", side_effect=PermissionError('Disco pieno')):
            results, reports = run_batch((disk,), inventory, Backend(), Event(), events.append, self.root/'reports', 1)
        self.assertEqual(results[0].status, 'SUCCESS')
        self.assertTrue(reports[0].exists())
        self.assertEqual(events[-1]['disk_records'], ())
        self.assertIn('Registri delle singole unità non salvati', events[-1]['report_error'])

    def test_blocked_ssd_record_preserves_failed_eligibility_and_null_counts(self):
        disk = replace(self.disk, kind='SSD', identity_source='ATA', firmware_model='HDD di prova')
        inventory = Inventory((disk,), True, simulated=True)
        events = []
        class Backend:
            def scan(self):
                return inventory
            def open_session(self, d):
                raise AssertionError('An unsupported SSD must never be opened')
        results, _ = run_batch((disk,), inventory, Backend(), Event(), events.append, self.root/'reports', 1)
        self.assertEqual(results[0].status, 'BLOCKED')
        paths = events[-1]['disk_records']
        self.assertEqual(len(paths), 1)
        payload = json.loads(paths[0].read_text())
        self.assertEqual(payload['result']['status'], 'BLOCKED')
        self.assertIsNone(payload['result']['written'])
        self.assertIsNone(payload['result']['verified'])
        self.assertTrue(payload['simulated'])


if __name__ == '__main__':
    unittest.main()
