"""USB topology, identity and veto checks; no physical disks or real PnP calls."""
from dataclasses import asdict, replace
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dejavu.core import Disk, Inventory, JobResult
from dejavu.usb_removal import (ConfigManager, DISK_CLASS, VOLUME_CLASS,
    helper_main, outcome, perform_removal, pnp_disks, remove_completed)


ROOT_A = r"USB\VID_174C&PID_55AA\DOCK-A"
ROOT_B = r"USB\VID_174C&PID_55AA\DOCK-B"
ID_A, ID_B, ID_C = (rf"SCSI\DISK&VEN_SABRENT&PROD_DUAL_SATA_BRIDGE\LUN-{n}" for n in range(3))


class Devices:
    def __init__(self, groups):
        self.groups = groups
        self.ejected = []
        self.veto = {}

    def storage_root(self, instance):
        return next((root for root, ids in self.groups.items() if instance in ids), None)

    def branch(self, root):
        return tuple(sorted([(root, "STORAGE")]
                            + [(identifier, DISK_CLASS) for identifier in self.groups[root]]))

    def eject(self, root, branch):
        if branch != self.branch(root):
            raise ValueError("Topology changed")
        self.ejected.append(root)
        return self.veto.get(root, (0, 0, ""))


class RemovalTests(unittest.TestCase):
    def setUp(self):
        self.system = Disk(0, "System", "SYSTEM", "system", 1048576, 512, "NVMe", "SSD",
                           protected_reasons=("Windows",))
        self.first = Disk(1, "SATA SSD", "SSD-A", "shared-bridge", 65536, 512, "USB", "SSD",
                          identity_source="ATA", firmware_model="SATA SSD", firmware_serial="SSD-A",
                          transport_serial="00000000000000000000", native_methods=("ATA_SECURITY_ENHANCED",))
        self.second = replace(self.first, number=2, serial="SSD-B", firmware_serial="SSD-B")
        self.third = replace(self.first, number=3, serial="SSD-C", firmware_serial="SSD-C")
        self.inventory = Inventory((self.system, self.first, self.second), True)
        self.mapping = {0: "SYSTEM-ID", 1: ID_A, 2: ID_B}
        self.manager = Devices({ROOT_A: (ID_A, ID_B)})
        self.results = [JobResult(d, "SUCCESS", "Erased") for d in (self.first, self.second)]

    def perform(self, results=None, inventory=None, mapping=None, manager=None):
        return list(perform_removal(results if results is not None else self.results,
            inventory if inventory is not None else self.inventory,
            mapping if mapping is not None else self.mapping,
            manager if manager is not None else self.manager))

    def test_two_sabrent_luns_with_zero_bridge_serial_are_ejected_once_together(self):
        records = self.perform()
        self.assertEqual(self.manager.ejected, [ROOT_A])
        self.assertEqual(records[0]["disk_numbers"], [1, 2])
        self.assertEqual(records[0]["status"], "EJECTED")

    def test_same_dock_unselected_second_disk_prevents_all_removal(self):
        records = self.perform(results=self.results[:1])
        self.assertFalse(self.manager.ejected)
        self.assertEqual(records[0]["status"], "SKIPPED")
        self.assertIn("non selezionati", records[0]["message"])

    def test_incomplete_cancelled_blocked_or_warning_companion_keeps_whole_dock(self):
        for status, warnings in (("FAILED", []), ("CANCELLED", []), ("BLOCKED", []), ("SUCCESS", ["Cleanup failed"])):
            with self.subTest(status=status, warnings=warnings):
                self.results[1].status, self.results[1].warnings = status, warnings
                records = self.perform()
                self.assertFalse(self.manager.ejected)
                self.assertEqual(records[0]["status"], "SKIPPED")

    def test_protected_companion_cannot_be_ejected_even_with_success_record(self):
        for reason in ("Windows", "Programma o rapporti in uso", "File di paging in uso"):
            with self.subTest(reason=reason):
                current = replace(self.second, protected_reasons=(reason,))
                records = self.perform(inventory=replace(self.inventory, disks=(self.system, self.first, current)))
                self.assertFalse(self.manager.ejected)
                self.assertEqual(records[0]["status"], "SKIPPED")

    def test_readonly_companion_prevents_whole_dock_removal(self):
        current = replace(self.second, read_only=True)
        self.perform(inventory=replace(self.inventory, disks=(self.system, self.first, current)))
        self.assertFalse(self.manager.ejected)

    def test_replaced_or_missing_usb_target_aborts_before_any_eject(self):
        for disks, mapping in (
                ((self.system, self.first, replace(self.second, serial="OTHER")), self.mapping),
                ((self.system, self.first), {0: "SYSTEM-ID", 1: ID_A})):
            with self.subTest(disks=disks):
                with self.assertRaises(ValueError):
                    self.perform(inventory=replace(self.inventory, disks=disks), mapping=mapping)
                self.assertFalse(self.manager.ejected)

    def test_more_native_disk_children_than_windows_records_prevents_removal(self):
        self.manager.groups[ROOT_A] = (ID_A, ID_B, "INVISIBLE-DISK-ID")
        records = self.perform()
        self.assertFalse(self.manager.ejected)
        self.assertEqual(records[0]["status"], "SKIPPED")

    def test_disagreement_between_get_disk_and_cim_or_protection_aborts(self):
        cases = [
            (self.inventory, {**self.mapping, 9: "EXTRA"}),
            (replace(self.inventory, protection_ok=False), self.mapping),
            (replace(self.inventory, error="Incomplete scan"), self.mapping),
            (replace(self.inventory, disks=(self.first, self.second)), {1: ID_A, 2: ID_B}),
        ]
        for inventory, mapping in cases:
            with self.subTest(inventory=inventory, mapping=mapping):
                with self.assertRaises(ValueError):
                    self.perform(inventory=inventory, mapping=mapping)
                self.assertFalse(self.manager.ejected)

    def test_placeholder_or_duplicate_firmware_identity_prevents_removal(self):
        for serial in ("000000", "SSD-A"):
            disk = replace(self.second, serial=serial)
            results = [self.results[0], JobResult(disk, "SUCCESS", "")]
            self.perform(results=results, inventory=replace(self.inventory, disks=(self.system, self.first, disk)))
            self.assertFalse(self.manager.ejected)

    def test_offline_volumes_and_security_changes_do_not_make_successful_disk_another_identity(self):
        disks = tuple(replace(d, offline=True, volume_paths=(), security_state=("FROZEN",))
                      if not d.protected else d for d in self.inventory.disks)
        records = self.perform(inventory=replace(self.inventory, disks=disks))
        self.assertEqual(records[0]["status"], "EJECTED")

    def test_failed_dock_does_not_prevent_separate_successful_dock_removal(self):
        inventory = replace(self.inventory, disks=(*self.inventory.disks, self.third))
        results = [*self.results, JobResult(self.third, "SUCCESS", "")]
        results[1].status = "FAILED"
        manager = Devices({ROOT_A: (ID_A, ID_B), ROOT_B: (ID_C,)})
        records = self.perform(results, inventory, {**self.mapping, 3: ID_C}, manager)
        self.assertEqual(manager.ejected, [ROOT_B])
        self.assertEqual({r["status"] for r in records}, {"SKIPPED", "EJECTED"})

    def test_windows_veto_is_recorded_once_without_force_or_retry(self):
        self.manager.veto[ROOT_A] = (0x17, 5, "Opened by another program")
        records = self.perform()
        self.assertEqual(self.manager.ejected, [ROOT_A])
        self.assertEqual(records[0]["status"], "NOT_CONFIRMED")
        self.assertEqual(records[0]["veto_type"], 5)
        self.assertEqual(records[0]["configret"], 0x17)
        self.assertIn("ancora in uso", records[0]["message"])

    def test_internal_sata_is_not_considered_for_removal(self):
        disk = replace(self.first, bus="SATA")
        self.assertEqual(self.perform(results=[JobResult(disk, "SUCCESS", "")]), [])
        self.assertFalse(self.manager.ejected)

    def test_unsupported_usb_has_explicit_non_ejected_outcome(self):
        self.manager.groups = {}
        records = self.perform()
        self.assertTrue(all(r["status"] == "SKIPPED" for r in records))
        self.assertFalse(self.manager.ejected)

    def test_pnp_association_rejects_duplicates_missing_values_and_wrong_shapes(self):
        for rows in ([{"Number": 1, "InstanceId": ID_A}] * 2,
                     [{"Number": 1, "InstanceId": ID_A}, {"Number": 2, "InstanceId": ID_A}],
                     [{"Number": 1, "InstanceId": ""}], [{"Number": True, "InstanceId": ID_A}], {}):
            with self.subTest(rows=rows), patch("dejavu.usb_removal.powershell", return_value=json.dumps({"Disks": rows})):
                with self.assertRaises(ValueError):
                    pnp_disks()

    def test_demo_cancellation_or_no_success_never_launch_windows_helper(self):
        cancelled = Event(); cancelled.set()
        simulated = [JobResult(replace(self.first, simulated=True), "SUCCESS", "")]
        failed = [JobResult(self.first, "FAILED", "")]
        with patch("dejavu.usb_removal.subprocess.run") as run:
            for results, cancel in ((self.results, cancelled), (simulated, Event()), (failed, Event()),
                                    ([JobResult(replace(self.first, bus="SATA"), "SUCCESS", "")], Event())):
                records = remove_completed(results, Path("app.exe"), Path("reports"), cancel)
                self.assertFalse(any(r["status"] == "EJECTED" for r in records))
            run.assert_not_called()

    def test_source_and_frozen_helpers_receive_only_usb_and_use_bounded_process(self):
        for frozen in (False, True):
            with self.subTest(frozen=frozen):
                def run(command, **options):
                    path = Path(command[-1])
                    request = json.loads(path.read_text())
                    self.assertEqual([r["disk"]["number"] for r in request["results"]], [1, 2])
                    self.assertEqual(options["timeout"], 90)
                    self.assertTrue(options["check"])
                    self.assertEqual(command[0], sys.executable)
                    self.assertEqual(command[-2], "--rimozione-usb-interna")
                    self.assertEqual(len(command), 3 if frozen else 4)
                    if not frozen:
                        self.assertTrue(Path(command[1]).is_file())
                    path.with_name("risposta.json").write_text(json.dumps({"complete": True, "records": [
                        outcome([1, 2], "EJECTED", "Confirmed", ROOT_A)]}))
                with patch("dejavu.usb_removal.subprocess.run", side_effect=run), patch.object(sys, "frozen", frozen, create=True):
                    records = remove_completed(self.results, Path("app.exe"), Path("reports"), Event())
                self.assertEqual(records[0]["status"], "EJECTED")

    def test_timeout_retains_first_dock_confirmation_and_marks_remaining_as_unknown(self):
        def run(command, **options):
            Path(command[-1]).with_name("risposta.json").write_text(json.dumps({"complete": False, "records": [
                outcome([1], "EJECTED", "Confirmed", ROOT_A)]}))
            raise subprocess.TimeoutExpired(command, options["timeout"])
        with patch("dejavu.usb_removal.subprocess.run", side_effect=run):
            records = remove_completed(self.results, Path("app.exe"), Path("reports"), Event())
        self.assertEqual([r["status"] for r in records], ["EJECTED", "NOT_CONFIRMED"])
        self.assertEqual(records[1]["disk_numbers"], [2])
        self.assertIn("90 secondi", records[1]["message"])

    def test_child_pipeline_saves_removal_results_and_uses_fresh_protected_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / "richiesta.json"
            request.write_text(json.dumps({"format": 1, "app_path": "app.exe", "report_path": "reports",
                "results": [{"disk": asdict(r.disk), "status": r.status, "warnings": []} for r in self.results]}))
            scanner = Mock(); scanner.scan.return_value = self.inventory
            with patch("dejavu.usb_removal.os", SimpleNamespace(name="nt")), \
                    patch("dejavu.usb_removal.WindowsInventory", return_value=scanner), \
                    patch("dejavu.usb_removal.pnp_disks", return_value=self.mapping), \
                    patch("dejavu.usb_removal.ConfigManager", return_value=self.manager):
                self.assertEqual(helper_main(request), 0)
            payload = json.loads(request.with_name("risposta.json").read_text())
            self.assertTrue(payload["complete"])
            self.assertEqual(payload["records"][0]["status"], "EJECTED")
            scanner.scan.assert_called_once_with()

    def test_helper_mode_bypasses_main_mutex_and_elevation_without_starting_gui(self):
        import main
        with patch("main.enable_dpi_awareness"), patch("main.WindowsInstance") as mutex, \
                patch("main.elevate") as elevate, patch("main.run_application") as application, \
                patch("dejavu.usb_removal.helper_main", return_value=0) as helper:
            self.assertEqual(main.main(["--rimozione-usb-interna", "request.json"]), 0)
            helper.assert_called_once_with(Path("request.json"))
            mutex.assert_not_called()
            elevate.assert_not_called()
            application.assert_not_called()


class NativeTopologyTests(unittest.TestCase):
    def setUp(self):
        self.manager = ConfigManager.__new__(ConfigManager)
        self.names = {1: ID_A, 2: ROOT_A, 3: r"USB\ROOT_HUB30\ROOT", 4: ID_B, 5: r"STORAGE\VOLUME\TEST"}
        self.manager.locate = lambda identifier: next(n for n, text in self.names.items() if text == identifier)
        self.manager.identifier = lambda n: self.names[n]
        self.parents = {1: 2, 4: 2, 2: 3}
        self.children = {2: 1, 1: 5}
        self.siblings = {1: 4}
        self.props = {(2, 5): "UASPSTOR", (2, 16): 4, (3, 5): "USBHUB3", (3, 16): 4,
                      (2, 9): "STORAGE", (1, 9): DISK_CLASS, (4, 9): DISK_CLASS, (5, 9): VOLUME_CLASS}
        self.manager.property = lambda node, key: self.props[node, key]
        self.manager.related = lambda fn, n: {"CM_Get_Parent": self.parents, "CM_Get_Child": self.children,
                                            "CM_Get_Sibling": self.siblings}[fn].get(n)

    def test_native_walk_finds_only_storage_root_and_all_disk_and_volume_children(self):
        self.assertEqual(self.manager.storage_root(ID_A), ROOT_A)
        branch = self.manager.branch(ROOT_A)
        self.assertEqual({i for i, c in branch if c == DISK_CLASS}, {ID_A, ID_B})
        self.assertIn((self.names[5], VOLUME_CLASS), branch)

    def test_hubs_composite_services_and_nonremovable_nodes_never_become_eject_target(self):
        for service, capabilities in (("USBHUB3", 4), ("USBCCGP", 4), ("UASPSTOR", 0)):
            with self.subTest(service=service, capabilities=capabilities):
                self.props[2, 5], self.props[2, 16] = service, capabilities
                self.assertIsNone(self.manager.storage_root(ID_A))
                with self.assertRaises(ValueError):
                    self.manager.branch(ROOT_A)

    def test_nonstorage_child_or_topology_cycle_prevents_removal(self):
        self.props[5, 9] = "HID"
        with self.assertRaises(ValueError):
            self.manager.branch(ROOT_A)
        self.props[5, 9] = VOLUME_CLASS
        self.siblings[4] = 1
        with self.assertRaises(ValueError):
            self.manager.branch(ROOT_A)

    def test_only_zero_return_code_is_success_and_native_veto_buffer_is_preserved(self):
        def request(node, veto, name, length, flags):
            self.assertEqual((node, length, flags), (2, 260, 0))
            ctypes.cast(veto, ctypes.POINTER(ctypes.c_uint32))[0] = 5
            name.value = "Blocking device"
            return 0x17
        function = Mock(side_effect=request)
        self.manager.api = SimpleNamespace(CM_Request_Device_EjectW=function)
        branch = self.manager.branch(ROOT_A)
        self.assertEqual(self.manager.eject(ROOT_A, branch), (0x17, 5, "Blocking device"))
        function.assert_called_once()
        self.siblings[1] = None
        with self.assertRaises(ValueError):
            self.manager.eject(ROOT_A, branch)
        self.assertEqual(function.call_count, 1)

    def test_windows_registry_properties_use_byte_lengths_and_utf16(self):
        manager = ConfigManager.__new__(ConfigManager)
        values = {5: (1, "UASPStor\0".encode("utf-16-le")), 16: (4, (4).to_bytes(4, "little"))}
        def read(node, key, kind, buffer, length, flags):
            value_type, data = values[key]
            ctypes.cast(kind, ctypes.POINTER(ctypes.c_uint32))[0] = value_type
            size = ctypes.cast(length, ctypes.POINTER(ctypes.c_uint32))
            if buffer is None:
                size[0] = len(data)
                return 0x1A
            self.assertGreaterEqual(size[0], len(data))
            ctypes.memmove(buffer, data, len(data))
            size[0] = len(data)
            return 0
        manager.api = SimpleNamespace(CM_Get_DevNode_Registry_PropertyW=read)
        self.assertEqual(manager.property(2, 5), "UASPSTOR")
        self.assertEqual(manager.property(2, 16), 4)
        values[5] = (7, b"x\0")
        with self.assertRaises(ValueError):
            manager.property(2, 5)

    def test_cfgmgr_functions_have_explicit_32bit_arguments_and_system_library_path(self):
        names = ("CM_Locate_DevNodeW", "CM_Get_Parent", "CM_Get_Child", "CM_Get_Sibling",
                 "CM_Get_Device_ID_Size", "CM_Get_Device_IDW", "CM_Get_DevNode_Registry_PropertyW",
                 "CM_Request_Device_EjectW")
        library = SimpleNamespace(**{name: Mock() for name in names})
        with patch("dejavu.usb_removal.os", SimpleNamespace(name="nt", environ={"SystemRoot": "Windows-root"})), \
                patch("dejavu.usb_removal.ctypes.WinDLL", return_value=library, create=True) as load:
            ConfigManager()
        self.assertEqual(Path(load.call_args.args[0]).parts[-2:], ("System32", "cfgmgr32.dll"))
        for name in names:
            self.assertEqual(getattr(library, name).restype, ctypes.c_uint32)
            self.assertTrue(getattr(library, name).argtypes)
        self.assertEqual(library.CM_Request_Device_EjectW.argtypes[0], ctypes.c_uint32)

    def test_missing_child_terminates_walk_but_unexpected_native_errors_abort(self):
        manager = ConfigManager.__new__(ConfigManager)
        manager.api = SimpleNamespace(CM_Get_Child=Mock(return_value=0x0D))
        self.assertIsNone(manager.related("CM_Get_Child", 1))
        manager.api.CM_Get_Child.return_value = 0x13
        with self.assertRaises(OSError):
            manager.related("CM_Get_Child", 1)


if __name__ == "__main__":
    unittest.main()
