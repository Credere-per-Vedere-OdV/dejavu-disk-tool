"""Erasure must finish and evidence must be durable before any USB removal."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

from dejavu.core import Disk, Inventory
from dejavu.engine import run_batch
from dejavu.simulation import FileSession
from dejavu.usb_removal import outcome


class BatchRemovalTests(unittest.TestCase):
    def setUp(self):
        awake = patch("dejavu.engine.KeepAwake")
        awake.start()
        self.addCleanup(awake.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = Disk(0, "Windows", "SYS", "sys", 65536, 512, "SATA", "SSD",
                           protected_reasons=("Windows",))
        self.disk = Disk(1, "File-backed HDD", "TEST-USB", "usb", 65536, 512, "USB", "HDD",
                         identity_source="ATA", firmware_model="File-backed HDD")
        self.path = self.root / "owned-test-file.bin"
        self.path.write_bytes(b'\xa5' * self.disk.size)
        self.inventory = Inventory((self.system, self.disk), True)
        inventory, path = self.inventory, self.path
        class Backend:
            def scan(self):
                return inventory
            def open_session(self, disk):
                return FileSession(path)
        self.backend = Backend()
        self.backend.remove_completed = Mock(return_value=[outcome([1], "EJECTED", "Confirmed")])
        self.events = []

    def run_batch(self, cancel=None):
        return run_batch((self.disk,), self.inventory, self.backend, cancel or Event(),
                         self.events.append, self.root / "reports", 1)

    def test_removal_waits_for_last_worker_to_close_and_final_report_to_be_saved(self):
        second = replace(self.disk, number=2, serial="SECOND")
        inventory = replace(self.inventory, disks=(*self.inventory.disks, second))
        other_path = self.root / "other-owned-file.bin"
        other_path.write_bytes(b'\xa5' * second.size)
        waiting, release = Event(), Event()
        sessions, output = [], []
        class Paused(FileSession):
            def rewind(self):
                super().rewind()
                waiting.set()
                if not release.wait(5):
                    raise TimeoutError("Reader not released")
        def open_session(disk):
            session = Paused(other_path) if disk.number == 2 else FileSession(self.path)
            sessions.append(session)
            return session
        self.backend.scan = lambda: inventory
        self.backend.open_session = open_session
        def remove(results, cancel):
            self.assertEqual(len(sessions), 2)
            self.assertTrue(all(session.file.closed for session in sessions))
            reports = list((self.root / "reports").glob("Dejavu-*.json"))
            self.assertEqual(len(reports), 1)
            initial = json.loads(reports[0].read_text())
            self.assertEqual({r["status"] for r in initial["results"]}, {"SUCCESS"})
            self.assertEqual(len(initial["results"]), 2)
            self.assertEqual(initial["safe_removal"], [])
            self.assertTrue(reports[0].with_suffix(".html").exists())
            return [outcome([1, 2], "EJECTED", "Confirmed")]
        self.backend.remove_completed.side_effect = remove
        thread = Thread(target=lambda: output.append(run_batch((self.disk, second), inventory,
            self.backend, Event(), self.events.append, self.root / "reports", 2)))
        thread.start()
        try:
            self.assertTrue(waiting.wait(2))
            self.backend.remove_completed.assert_not_called()
            self.assertFalse(any(e["type"] == "batch_done" for e in self.events))
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.backend.remove_completed.assert_called_once()
        final = json.loads(output[0][1][1].read_text())
        self.assertEqual(final["safe_removal"][0]["status"], "EJECTED")
        self.assertEqual([r["status"] for r in final["results"]], ["SUCCESS", "SUCCESS"])
        self.assertEqual(self.events[-1]["type"], "batch_done")

    def test_report_save_failure_prevents_removal_without_losing_erasure_outcome(self):
        with patch("dejavu.engine.save_reports", side_effect=PermissionError("Disk full")):
            results, reports = self.run_batch()
        self.backend.remove_completed.assert_not_called()
        self.assertIsNone(reports)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(self.events[-1]["removal_results"][0]["status"], "SKIPPED")

    def test_progressive_record_failure_also_prevents_removal(self):
        with patch("dejavu.engine.save_disk_record", side_effect=PermissionError("Record not saved")):
            results, reports = self.run_batch()
        self.backend.remove_completed.assert_not_called()
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertTrue(reports[0].is_file())
        self.assertEqual(json.loads(reports[1].read_text())["safe_removal"][0]["status"], "SKIPPED")

    def test_removal_exception_keeps_success_separate_in_html_json_and_event(self):
        self.backend.remove_completed.side_effect = OSError("PnP failed")
        results, reports = self.run_batch()
        payload = json.loads(reports[1].read_text())
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertFalse(results[0].warnings)
        self.assertEqual(payload["results"][0]["status"], "SUCCESS")
        self.assertEqual(payload["safe_removal"][0]["status"], "NOT_CONFIRMED")
        self.assertIn("RIMOZIONE NON CONFERMATA", reports[0].read_text())
        self.assertEqual(self.events[-1]["removal_results"], payload["safe_removal"])

    def test_cancelled_batch_does_not_attempt_removal(self):
        cancel = Event(); cancel.set()
        self.run_batch(cancel)
        self.backend.remove_completed.assert_not_called()
        self.assertEqual(self.events[-1]["removal_results"][0]["status"], "SKIPPED")

    def test_simulated_batch_never_calls_real_removal_backend(self):
        self.disk = replace(self.disk, simulated=True)
        self.inventory = replace(self.inventory, disks=(self.system, self.disk), simulated=True)
        self.backend.scan = lambda: self.inventory
        self.run_batch()
        self.backend.remove_completed.assert_not_called()
        self.assertEqual(self.events[-1]["removal_results"][0]["status"], "SIMULATED")

    def test_internal_sata_does_not_request_usb_removal(self):
        self.disk = replace(self.disk, bus="SATA")
        self.inventory = replace(self.inventory, disks=(self.system, self.disk))
        self.backend.scan = lambda: self.inventory
        self.run_batch()
        self.backend.remove_completed.assert_not_called()
        self.assertEqual(self.events[-1]["removal_results"], [])


if __name__ == "__main__":
    unittest.main()
