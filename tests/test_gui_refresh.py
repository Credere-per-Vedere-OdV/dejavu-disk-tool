"""Exercise selection during a real inventory worker, without Tk or disk I/O."""
from dataclasses import replace
from queue import Queue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dejavu.core import Disk, Inventory, JobResult
from dejavu.gui import Application, DiskRow
from dejavu.usb_removal import outcome


class Value:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.options = {}
        self.disabled = False
        self.destroyed = False

    def configure(self, **options):
        self.options.update(options)

    def cget(self, name):
        return self.options.get(name, "")

    def state(self, states):
        self.disabled = "disabled" in states

    def destroy(self):
        self.destroyed = True


class Row:
    set_enabled = DiskRow.set_enabled

    def __init__(self, disk):
        self.disk = disk
        self.selected = Value()
        self.check = Widget()
        self.frame = Widget()
        self.status = Widget()
        self.detail = Widget()


class PausedInventory:
    def __init__(self, inventory):
        self.inventory = inventory
        self.entered = Event()
        self.release = Event()
        self.error = None

    def scan(self):
        self.entered.set()
        if not self.release.wait(3):
            raise TimeoutError("Inventory test worker was not released")
        if self.error:
            raise self.error
        return self.inventory


class GuiRefreshTests(unittest.TestCase):
    def setUp(self):
        self.system = Disk(0, "System", "SYSTEM", "id-system", 65536, 512,
                           "NVMe", "SSD", protected_reasons=("Windows",))
        self.first = Disk(1, "SSD di prova", "SSD-A", "bridge-id", 65536, 512,
                          "USB", "SSD", identity_source="ATA",
                          firmware_model="SSD di prova", firmware_serial="SSD-A",
                          native_methods=("ATA_SECURITY_ENHANCED",))
        self.second = replace(self.first, number=2, serial="SSD-B", firmware_serial="SSD-B")
        self.inventory = Inventory((self.system, self.first, self.second), True)
        factory = patch("dejavu.gui.DiskRow", side_effect=lambda parent, disk, changed, safe: Row(disk))
        factory.start()
        self.addCleanup(factory.stop)
        self.app, self.backend = self.make_app()

    def make_app(self, inventory=None):
        inventory = inventory if inventory is not None else self.inventory
        backend = PausedInventory(inventory)
        self.addCleanup(backend.release.set)
        app = Application.__new__(Application)
        app.root = SimpleNamespace(after=Mock())
        app.backend = backend
        app.events = Queue()
        app.inventory = inventory
        app.rows = {disk.number: Row(disk) for disk in inventory.disks}
        app.list_frame = object()
        app.demo = False
        app.busy = app.scanning = app.confirming = False
        app.background_scan = app.have_results = app.closing = False
        app.unavailable_scan_count = 0
        app.automatic_scan_paused = False
        app.finalizing = False
        for name in ("connection", "summary", "start_button", "select_lot", "refresh", "stop_button", "open_button"):
            setattr(app, name, Widget())
        app._controls()
        return app, backend

    def begin_background(self):
        self.app._automatic_scan()
        self.assertTrue(self.backend.entered.wait(1))
        self.assertTrue(self.app.scanning)

    def complete(self, app=None, backend=None):
        app, backend = app or self.app, backend or self.backend
        backend.release.set()
        event = app.events.get(timeout=2)
        self.assertEqual(event["type"], "inventory")
        app.show_inventory(event["inventory"])

    def test_polling_keeps_checkboxes_usable_and_preserves_rows_and_selection(self):
        original_rows = dict(self.app.rows)
        self.backend.inventory = replace(self.inventory, scanned_at="new scan")
        self.begin_background()
        self.assertFalse(self.app.rows[1].check.disabled)
        self.assertFalse(self.app.rows[2].check.disabled)
        self.assertTrue(self.app.rows[0].check.disabled)
        self.app.rows[1].selected.set(True)
        self.app.selection_changed()
        self.assertEqual(self.app.start_button.options["state"], "disabled")
        with patch.object(self.app, "confirm") as confirm:
            self.app.start()
            confirm.assert_not_called()
        self.complete()
        for number, row in original_rows.items():
            self.assertIs(self.app.rows[number], row)
            self.assertFalse(row.frame.destroyed)
        self.assertEqual([disk.serial for disk in self.app.selected()], ["SSD-A"])
        self.assertEqual(self.app.start_button.options["state"], "normal")
        self.assertIs(self.app.inventory, self.backend.inventory)

    def test_select_batch_remains_available_during_background_refresh(self):
        self.begin_background()
        self.assertEqual(self.app.select_lot.options["state"], "normal")
        self.app.select_batch()
        self.assertEqual({disk.serial for disk in self.app.selected()}, {"SSD-A", "SSD-B"})
        self.assertFalse(self.app.rows[0].selected.get())
        self.assertEqual(self.app.start_button.options["state"], "disabled")
        self.complete()
        self.assertEqual(len(self.app.selected()), 2)
        self.assertEqual(self.app.start_button.options["state"], "normal")

    def test_replacement_at_same_disk_number_does_not_inherit_selection(self):
        replacement = replace(self.first, serial="SSD-C", firmware_serial="SSD-C")
        self.backend.inventory = replace(self.inventory, disks=(self.system, replacement, self.second))
        self.begin_background()
        self.app.rows[1].selected.set(True)
        self.app.rows[2].selected.set(True)
        self.complete()
        self.assertFalse(self.app.rows[1].selected.get())
        self.assertEqual([disk.serial for disk in self.app.selected()], ["SSD-B"])

    def test_selection_is_removed_if_fresh_protection_or_eligibility_changes(self):
        unsafe = [
            replace(self.first, protected_reasons=("Programma in uso",)),
            replace(self.first, read_only=True),
            replace(self.first, kind="UNKNOWN", native_methods=()),
            replace(self.first, security_state=("FROZEN",)),
            replace(self.first, serial="SSD-B", firmware_serial="SSD-B"),
        ]
        for changed in unsafe:
            with self.subTest(disk=changed):
                app, backend = self.make_app()
                backend.inventory = replace(self.inventory, disks=(self.system, changed, self.second))
                app.scan(background=True)
                self.assertTrue(backend.entered.wait(1))
                app.rows[1].selected.set(True)
                self.complete(app, backend)
                self.assertFalse(app.rows[1].selected.get())
                self.assertEqual(app.start_button.options["state"], "disabled")

    def test_failed_background_scan_clears_selection_and_blocks_start(self):
        self.backend.error = RuntimeError("Rilevamento fallito")
        self.begin_background()
        self.app.rows[1].selected.set(True)
        self.complete()
        self.assertFalse(self.app.inventory.protection_ok)
        self.assertFalse(self.app.selected())
        self.assertEqual(self.app.start_button.options["state"], "disabled")
        self.assertEqual(self.app.select_lot.options["state"], "disabled")
        self.assertIn("Rilevamento fallito", self.app.connection.options["text"])

    def test_unchanged_refresh_revalidates_a_newly_checked_unsupported_drive(self):
        readonly = replace(self.first, read_only=True)
        inventory = replace(self.inventory, disks=(self.system, readonly, self.second))
        app, backend = self.make_app(inventory)
        app.scan(background=True)
        self.assertTrue(backend.entered.wait(1))
        original_row = app.rows[1]
        original_row.selected.set(True)
        self.complete(app, backend)
        self.assertIs(app.rows[1], original_row)
        self.assertFalse(original_row.selected.get())
        self.assertEqual(app.start_button.options["state"], "disabled")

    def test_initial_and_manual_detection_still_block_selection(self):
        for manual in (False, True):
            with self.subTest(manual=manual):
                app, backend = self.make_app()
                app.scan(manual=manual)
                self.assertTrue(backend.entered.wait(1))
                self.assertTrue(all(row.check.disabled for row in app.rows.values()))
                self.assertEqual(app.select_lot.options["state"], "disabled")
                self.complete(app, backend)
                self.assertFalse(app.rows[1].check.disabled)
                self.assertTrue(app.rows[0].check.disabled)

    def test_automatic_refresh_respects_selection_jobs_confirmation_and_results(self):
        for condition in ("selected", "busy", "confirming", "have_results", "closing"):
            with self.subTest(condition=condition):
                app, backend = self.make_app()
                if condition == "selected":
                    app.rows[1].selected.set(True)
                else:
                    setattr(app, condition, True)
                app._automatic_scan()
                self.assertFalse(backend.entered.is_set())
                self.assertFalse(app.scanning)

    def test_explicit_refresh_resets_completed_rows_even_with_same_disks(self):
        self.app.have_results = True
        original = self.app.rows[1]
        original.status.configure(text="ESITO PRECEDENTE")
        self.app.scan(manual=True)
        self.assertTrue(self.backend.entered.wait(1))
        self.complete()
        self.assertFalse(self.app.have_results)
        self.assertIsNot(self.app.rows[1], original)
        self.assertTrue(original.frame.destroyed)
        self.assertFalse(self.app.selected())

    def test_new_drive_is_added_unchecked_without_losing_existing_selection(self):
        new = replace(self.first, number=3, serial="SSD-C", firmware_serial="SSD-C")
        self.backend.inventory = replace(self.inventory, disks=(*self.inventory.disks, new))
        self.begin_background()
        self.app.rows[1].selected.set(True)
        self.complete()
        self.assertIn(3, self.app.rows)
        self.assertFalse(self.app.rows[3].selected.get())
        self.assertEqual([disk.serial for disk in self.app.selected()], ["SSD-A"])

    def test_three_system_only_scans_pause_further_automatic_detection(self):
        empty = replace(self.inventory, disks=(self.system,))
        app, backend = self.make_app(empty)
        with patch.object(backend, "scan", wraps=backend.scan) as scan:
            for _ in range(3):
                app._automatic_scan()
                self.complete(app, backend)
            for _ in range(10):
                app._automatic_scan()
            self.assertEqual(scan.call_count, 3)
        self.assertTrue(app.automatic_scan_paused)
        self.assertIn("Ricerca automatica sospesa", app.connection.options["text"])
        self.assertIn("Rileva dischi", app.connection.options["text"])
        self.assertEqual(app.refresh.options["state"], "normal")
        self.assertEqual(app.start_button.options["state"], "disabled")
        self.assertTrue(app.rows[0].check.disabled)

    def test_three_scan_errors_pause_without_enabling_erasure(self):
        self.backend.error = RuntimeError("Windows non risponde")
        for _ in range(3):
            self.app._automatic_scan()
            self.complete()
        self.assertTrue(self.app.automatic_scan_paused)
        self.assertFalse(self.app.inventory.protection_ok)
        self.assertIn("Windows non risponde", self.app.connection.options["text"])
        self.assertIn("Ricerca automatica sospesa", self.app.connection.options["text"])
        self.assertEqual(self.app.start_button.options["state"], "disabled")
        with patch.object(self.app, "scan") as scan:
            self.app._automatic_scan()
            scan.assert_not_called()

    def test_manual_retry_after_pause_detects_a_drive_without_selecting_it(self):
        empty = replace(self.inventory, disks=(self.system,))
        app, backend = self.make_app(empty)
        for _ in range(3):
            app._automatic_scan()
            self.complete(app, backend)
        self.assertTrue(app.automatic_scan_paused)
        backend.inventory = self.inventory
        app.scan(manual=True)
        self.complete(app, backend)
        self.assertFalse(app.automatic_scan_paused)
        self.assertEqual(app.unavailable_scan_count, 0)
        self.assertEqual(set(app.rows), {0, 1, 2})
        self.assertFalse(app.selected())
        self.assertFalse(app.rows[1].check.disabled)
        self.assertTrue(app.rows[0].check.disabled)

    def test_a_detected_drive_resets_the_empty_scan_budget(self):
        empty = replace(self.inventory, disks=(self.system,))
        app, backend = self.make_app(empty)
        for _ in range(2):
            app._automatic_scan()
            self.complete(app, backend)
        backend.inventory = self.inventory
        app._automatic_scan()
        self.complete(app, backend)
        self.assertEqual(app.unavailable_scan_count, 0)
        self.assertFalse(app.automatic_scan_paused)
        backend.inventory = empty
        for _ in range(2):
            app._automatic_scan()
            self.complete(app, backend)
        self.assertFalse(app.automatic_scan_paused)
        app._automatic_scan()
        self.complete(app, backend)
        self.assertTrue(app.automatic_scan_paused)

    def test_manual_retry_without_drives_has_a_new_bounded_budget(self):
        empty = replace(self.inventory, disks=(self.system,))
        app, backend = self.make_app(empty)
        for _ in range(3):
            app._automatic_scan()
            self.complete(app, backend)
        app.scan(manual=True)
        self.complete(app, backend)
        self.assertEqual(app.unavailable_scan_count, 1)
        self.assertFalse(app.automatic_scan_paused)
        for _ in range(2):
            app._automatic_scan()
            self.complete(app, backend)
        self.assertTrue(app.automatic_scan_paused)

    def test_visible_drives_without_confirmed_protection_do_not_reset_budget(self):
        self.backend.inventory = replace(self.inventory, protection_ok=False,
                                         error="Protezione non confermata")
        for _ in range(3):
            self.app._automatic_scan()
            self.complete()
        self.assertTrue(self.app.automatic_scan_paused)
        self.assertTrue(all(row.check.disabled for row in self.app.rows.values()))
        self.assertEqual(self.app.start_button.options["state"], "disabled")

    def test_inventory_error_blocks_controls_even_with_a_true_protection_flag(self):
        self.app.show_inventory(replace(self.inventory, error="Rilevamento incompleto"))
        self.assertTrue(all(row.check.disabled for row in self.app.rows.values()))
        self.assertEqual(self.app.start_button.options["state"], "disabled")
        self.assertEqual(self.app.select_lot.options["state"], "disabled")
        self.assertIn("Cancellazione bloccata", self.app.connection.options["text"])

    def test_finalizing_event_keeps_app_busy_and_cannot_interrupt_or_close_removal(self):
        self.app.busy = True
        self.app.events.put({"type": "finalizing", "message": "Rimozione sicura USB in corso"})
        self.app._events()
        self.assertTrue(self.app.busy)
        self.assertTrue(self.app.finalizing)
        self.assertEqual(self.app.stop_button.cget("state"), "disabled")
        with patch("dejavu.gui.messagebox.askyesno") as ask:
            self.app.stop()
            self.app.close()
            ask.assert_not_called()
        self.assertFalse(self.app.closing)
        self.assertIn("Attendi", self.app.connection.cget("text"))

    def test_batch_completion_distinguishes_erased_disk_from_refused_removal(self):
        self.app.busy = self.app.finalizing = True
        results = [JobResult(self.first, "SUCCESS", "Erased"), JobResult(self.second, "SUCCESS", "Erased")]
        for status, message in (("EJECTED", "Docking espulsa"), ("NOT_CONFIRMED", "Ancora in uso")):
            with self.subTest(status=status):
                self.app.batch_done({"reports": None, "results": results, "report_error": "",
                    "removal_results": [outcome([1, 2], status, message)]})
                self.assertFalse(self.app.busy)
                self.assertFalse(self.app.finalizing)
                self.assertTrue(self.app.have_results)
                self.assertIn("2 completati", self.app.summary.cget("text"))
                self.assertIn(message, self.app.rows[1].detail.cget("text"))
                self.assertEqual(self.app.start_button.cget("state"), "disabled")
                if status == "EJECTED":
                    self.assertIn("Puoi spegnerle", self.app.connection.cget("text"))
                else:
                    self.assertIn("da controllare", self.app.connection.cget("text"))


if __name__ == "__main__":
    unittest.main()
