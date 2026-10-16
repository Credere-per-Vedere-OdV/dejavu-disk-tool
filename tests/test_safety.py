"""Tests use owned temporary files or Win32 fakes, never physical disks."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event, Lock
import ctypes
import json
import os
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from dejavu.core import Blocked, Disk, Inventory, JobResult, run_job, validate_target
from dejavu.engine import run_batch
from dejavu.inventory import parse_inventory, WindowsInventory
from dejavu.reports import save_reports
from dejavu.simulation import FileSession
from dejavu.windows_io import (NativeApi, RawSession, ata_identity, volume_disk_numbers,
                               AtaPassThrough, ScsiPassThroughDirect, FSCTL_LOCK_VOLUME,
                               IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, inspect_disk,
                               IOCTL_ATA_PASS_THROUGH, FSCTL_DISMOUNT_VOLUME,
                               DeviceError, LOCK_ATTEMPTS, LOCK_RETRY_DELAY)


def disk(number=1, size=12288, sector=512, **changes):
    target = Disk(number, "Disco di prova", f"SERIAL-{number}", f"ID-{number}",
                  size, sector, "SATA", "HDD", simulated=True)
    return replace(target, **changes)


def inventory(*targets):
    system = disk(0, protected_reasons=("Windows in esecuzione",), kind="SSD")
    return Inventory((system, *targets), True, simulated=True)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dejavu-test-")
        self.root = Path(self.temp.name)
        self.cancel = Event()
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def file(self, target):
        path = self.root / f"{target.number}.bin"
        path.write_bytes(bytes([0xAB]) * target.size)
        return path

    def run_one(self, target=None, session=None, fresh=None, cancel=None, block_size=8192):
        target = target or disk()
        path = self.file(target)
        factory = session if session is not None else lambda _: FileSession(path)
        scan = (lambda: fresh) if fresh is not None else lambda: inventory(target)
        result = run_job(target, scan, factory, cancel or self.cancel,
                         self.events.append, block_size=block_size)
        return result, path

    def assert_no_success(self, result, status="FAILED"):
        self.assertEqual(result.status, status)
        finished = [event for event in self.events if event["type"] == "result"]
        self.assertEqual(len(finished), 1)
        self.assertIs(finished[0]["result"], result)

    def test_full_overwrite_readback_includes_tail_and_4k_sectors(self):
        for sector in (512, 4096):
            with self.subTest(sector=sector):
                self.events.clear()
                target = disk(size=3 * 8192 + sector, sector=sector)
                result, path = self.run_one(target)
                self.assertEqual(result.status, "SUCCESS")
                self.assertEqual(result.written, target.size)
                self.assertEqual(result.verified, target.size)
                self.assertEqual(path.read_bytes(), bytes(target.size))
                self.assertEqual(sum(event["type"] == "result" for event in self.events), 1)

    def test_unprotected_internal_sata_and_usb_are_eligible(self):
        for bus in ("SATA", "USB"):
            target = disk(bus=bus)
            self.assertEqual(validate_target(target, inventory(target)), target)

    def test_system_boot_pagefile_and_program_disks_never_opened(self):
        for reason in ("Windows", "EFI in uso", "File di paging", "Programma o rapporti"):
            self.events.clear()
            target = disk(protected_reasons=(reason,))
            opening = Mock(side_effect=AssertionError("NON deve aprire il dispositivo"))
            result, path = self.run_one(target, session=opening)
            self.assert_no_success(result, "BLOCKED")
            opening.assert_not_called()
            self.assertEqual(path.read_bytes(), bytes([0xAB]) * target.size)

    def test_failed_system_detection_never_opens_a_target(self):
        opening = Mock()
        result, _ = self.run_one(session=opening, fresh=Inventory((), False, "Errore di rilevamento"))
        self.assert_no_success(result, "BLOCKED")
        opening.assert_not_called()

    def test_disconnected_or_replaced_disk_never_opens(self):
        for fresh in (inventory(), inventory(disk(serial="NUOVO")),
                      inventory(disk(unique_id="NUOVA-ID")), inventory(disk(size=16384))):
            self.events.clear()
            opening = Mock()
            result, _ = self.run_one(session=opening, fresh=fresh)
            self.assert_no_success(result, "BLOCKED")
            opening.assert_not_called()

    def test_ambiguous_disk_numbers_and_serials_are_blocked(self):
        for fresh in (inventory(disk(), disk()),
                      inventory(disk(), disk(2, serial="SERIAL-1"))):
            self.events.clear()
            opening = Mock()
            result, _ = self.run_one(session=opening, fresh=fresh)
            self.assert_no_success(result, "BLOCKED")
            opening.assert_not_called()

    def test_ssd_unknown_readonly_missing_serial_and_aggregates_are_blocked(self):
        for changes in ({"kind": "SSD"}, {"kind": "UNKNOWN"}, {"read_only": True},
                        {"serial": ""}, {"bus": "RAID"}, {"bus": "Virtual"},
                        {"bus": "StorageSpaces"}, {"bus": "FileBackedVirtual"}):
            self.events.clear()
            target = disk(**changes)
            opening = Mock()
            result, _ = self.run_one(target, session=opening)
            self.assert_no_success(result, "BLOCKED")
            opening.assert_not_called()

    def test_invalid_capacity_sector_and_block_alignment_block_before_open(self):
        for target, block in ((disk(size=0), 8192), (disk(size=513), 8192),
                              (disk(sector=1024), 8192), (disk(sector=4096), 512)):
            self.events.clear()
            opening = Mock()
            result, _ = self.run_one(target, session=opening, block_size=block)
            self.assert_no_success(result, "BLOCKED")
            opening.assert_not_called()

    def test_device_open_failure_cannot_report_success(self):
        opening = Mock(side_effect=PermissionError("Dispositivo in uso"))
        result, _ = self.run_one(session=opening)
        self.assert_no_success(result)
        self.assertEqual(result.written, 0)

    def test_short_write_is_failed_and_records_confirmed_bytes(self):
        class ShortWrite(FileSession):
            def write(self, data):
                return super().write(data[:512])
        result, path = self.run_one(session=lambda _: ShortWrite(self.root / "1.bin"))
        self.assert_no_success(result)
        self.assertEqual(result.written, 512)
        self.assertEqual(result.verified, 0)
        self.assertEqual(path.read_bytes()[512:], bytes([0xAB]) * (12288 - 512))

    def test_short_read_and_read_error_are_failed(self):
        class ShortRead(FileSession):
            def read(self, size):
                return super().read(size - 512)
        for factory in (lambda _: ShortRead(self.root / "1.bin"),
                        lambda _: FileSession(self.root / "1.bin", fail_read=True)):
            self.events.clear()
            result, _ = self.run_one(session=factory)
            self.assert_no_success(result)
            self.assertEqual(result.written, result.disk.size)
            self.assertEqual(result.verified, 0)

    def test_corrupt_readback_never_succeeds(self):
        class Corrupt(FileSession):
            def read(self, size):
                data = super().read(size)
                return b"\xFF" + data[1:]
        result, _ = self.run_one(session=lambda _: Corrupt(self.root / "1.bin"))
        self.assert_no_success(result)
        self.assertIn("Verifica fallita", result.message)

    def test_flush_and_finish_failures_never_succeed(self):
        class BadFlush(FileSession):
            def flush(self):
                raise IOError("Flush fallito")
        class BadFinish(FileSession):
            def finish(self):
                raise IOError("Chiusura fallita")
        for cls in (BadFlush, BadFinish):
            self.events.clear()
            result, _ = self.run_one(session=lambda _: cls(self.root / "1.bin"))
            self.assert_no_success(result)

    def test_device_length_changed_after_open_does_not_write(self):
        class OtherSize(FileSession):
            def __init__(self, path):
                super().__init__(path)
                self.size -= 512
        result, path = self.run_one(session=lambda _: OtherSize(self.root / "1.bin"))
        self.assert_no_success(result, "BLOCKED")
        self.assertEqual(result.written, 0)
        self.assertEqual(path.read_bytes(), bytes([0xAB]) * result.disk.size)

    def test_cancellation_before_start_does_not_open(self):
        self.cancel.set()
        opening = Mock()
        result, _ = self.run_one(session=opening)
        self.assert_no_success(result, "CANCELLED")
        opening.assert_not_called()

    def test_cancellation_during_write_and_verification_does_not_succeed(self):
        parent = self
        class StopWriting(FileSession):
            def write(self, data):
                count = super().write(data)
                parent.cancel.set()
                return count
        class StopVerifying(FileSession):
            def read(self, size):
                data = super().read(size)
                parent.cancel.set()
                return data
        for cls in (StopWriting, StopVerifying):
            self.cancel.clear()
            self.events.clear()
            result, _ = self.run_one(session=lambda _: cls(self.root / "1.bin"))
            self.assert_no_success(result, "CANCELLED")

    def test_cancel_after_last_verified_byte_is_still_not_success(self):
        parent = self
        class StopLastRead(FileSession):
            def read(self, size):
                data = super().read(size)
                if self.file.tell() == self.size:
                    parent.cancel.set()
                return data
        result, _ = self.run_one(session=lambda _: StopLastRead(self.root / "1.bin"))
        self.assert_no_success(result, "CANCELLED")
        self.assertEqual(result.verified, result.disk.size)

    def test_cleanup_warnings_survive_failed_job(self):
        class WarningOnExit(FileSession):
            def __exit__(self, *args):
                self.warnings.append("Disco lasciato offline")
                return super().__exit__(*args)
        result, _ = self.run_one(session=lambda _: WarningOnExit(self.root / "1.bin", fail_read=True))
        self.assert_no_success(result)
        self.assertEqual(result.warnings, ["Disco lasciato offline"])

    def test_parallel_failure_isolated_and_complete_report_written(self):
        targets = [disk(index, size=32768) for index in range(1, 5)]
        paths = {target.number: self.file(target) for target in targets}
        parent = self
        active = maximum = 0
        lock = Lock()
        class CountSession(FileSession):
            def __enter__(self):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                return super().__enter__()
            def __exit__(self, *args):
                nonlocal active
                with lock:
                    active -= 1
                return super().__exit__(*args)
        class Backend:
            def scan(self):
                return inventory(*targets)
            def open_session(self, target):
                return CountSession(paths[target.number], fail_read=target.number == 2, delay=0.03)
        results, reports = run_batch(targets, inventory(*targets), Backend(), Event(),
                                     self.events.append, self.root / "reports", 2)
        self.assertEqual(maximum, 2)
        self.assertEqual(active, 0)
        self.assertEqual({r.disk.number: r.status for r in results}, {1: "SUCCESS", 2: "FAILED", 3: "SUCCESS", 4: "SUCCESS"})
        self.assertEqual(len(json.loads(reports[1].read_text())["results"]), 4)
        self.assertEqual(sum(event["type"] == "batch_done" for event in self.events), 1)

    def test_report_failure_still_emits_per_disk_result_and_summary(self):
        target = disk()
        path = self.file(target)
        class Backend:
            def scan(self):
                return inventory(target)
            def open_session(self, _):
                return FileSession(path)
        with patch("dejavu.engine.save_reports", side_effect=PermissionError("Cartella non scrivibile")):
            results, reports = run_batch([target], inventory(target), Backend(), Event(),
                                         self.events.append, self.root, 1)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertIsNone(reports)
        self.assertIn("non è stato salvato", self.events[-1]["report_error"])

    def test_report_escapes_device_strings_and_keeps_coverage(self):
        target = disk(model="<script>alert(1)</script>", serial="<SERIAL>")
        result = JobResult(target, "SUCCESS", "<test>", target.size, target.size,
                           warnings=["<attenzione>"])
        html, report = save_reports(self.root, inventory(target), [result], 2)
        text = html.read_text()
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("success_warning", text)
        self.assertIn("SIMULAZIONE", text)
        payload = json.loads(report.read_text())
        self.assertTrue(payload["simulated"])
        self.assertEqual(payload["results"][0]["verified"], target.size)
        self.assertIn("Purge", payload["coverage"])


class InventoryAndNativeTests(unittest.TestCase):
    def payload(self):
        return {"ProtectionOK": True, "Disks": [
            {"Number": 0, "Model": "Windows", "Serial": "SYS", "UniqueId": "0", "Size": 1000000000,
             "SectorSize": 512, "Bus": "NVMe", "Kind": "SSD", "Protected": ["Windows"], "Volumes": [], "ReadOnly": False, "Offline": False},
            {"Number": 1, "Model": "Data", "Serial": "DATA", "UniqueId": "1", "Size": 12288,
             "SectorSize": 512, "Bus": "SATA", "Kind": "HDD", "Protected": [], "Volumes": ["\\\\?\\Volume{GUID}\\"], "ReadOnly": False, "Offline": False}]}

    def test_inventory_requires_explicit_protection_and_valid_flags(self):
        for change in ("ProtectionOK", "Protected", "ReadOnly", "Number"):
            payload = self.payload()
            if change == "ProtectionOK":
                payload[change] = False
            elif change == "Protected":
                payload["Disks"][0][change] = []
            elif change == "ReadOnly":
                del payload["Disks"][1][change]
            else:
                payload["Disks"][1][change] = 0
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                parse_inventory(payload)

    def test_inventory_keeps_internal_data_disk_and_volume_guids(self):
        result = parse_inventory(self.payload())
        self.assertTrue(result.protection_ok)
        self.assertFalse(result.disks[1].protected)
        self.assertEqual(result.disks[1].bus, "SATA")
        self.assertEqual(len(result.disks[1].volume_paths), 1)

    def test_powershell_failure_leaves_everything_blocked(self):
        with patch("dejavu.inventory.powershell", side_effect=RuntimeError("CIM non disponibile")):
            result = WindowsInventory(Path("."), Path(".")).scan()
        self.assertFalse(result.protection_ok)
        self.assertFalse(result.disks)
        self.assertIn("CIM", result.error)

    def test_conflicting_media_or_serial_cannot_be_hdd(self):
        for info in ({"number": 1, "size": 12288, "sector_size": 512, "kind": "SSD", "serial": "DATA", "evidence": "ATA"},
                     {"number": 1, "size": 12288, "sector_size": 512, "kind": "HDD", "serial": "DIFFERENT", "evidence": "ATA"}):
            with patch("dejavu.inventory.powershell", return_value=json.dumps(self.payload())), \
                 patch("dejavu.windows_io.inspect_disk", return_value=info):
                result = WindowsInventory(Path("."), Path(".")).scan()
            self.assertEqual(result.disks[1].kind, "UNKNOWN")

    def test_ata_rotation_rate_and_word_swapped_serial(self):
        for rate, kind in ((1, "SSD"), (5400, "HDD"), (7200, "HDD"), (0, "UNKNOWN"), (0xFFFF, "UNKNOWN")):
            data = bytearray(512)
            serial = b"SERIAL-123".ljust(20)
            data[20:40] = b"".join(serial[index:index + 2][::-1] for index in range(0, 20, 2))
            struct.pack_into("<H", data, 434, rate)
            result = ata_identity(data)
            self.assertEqual(result["serial"], "SERIAL-123")
            self.assertEqual(result["kind"], kind)
        with self.assertRaises(ValueError):
            ata_identity(bytes(511))

    def test_windows_64bit_structure_sizes(self):
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(AtaPassThrough), 48)
            self.assertEqual(ctypes.sizeof(ScsiPassThroughDirect), 56)

    def test_ata_probe_issues_identify_input_header_only_and_checks_data_length(self):
        api = object.__new__(NativeApi)
        header = AtaPassThrough()
        header.Length = ctypes.sizeof(header)
        header.DataTransferLength = 512
        header.CurrentTaskFile[6] = 0x50
        api.ioctl = Mock(return_value=bytes(header) + bytes(512))
        self.assertEqual(api.identify_ata("fake"), bytes(512))
        handle, code, request, out_size = api.ioctl.call_args.args
        self.assertEqual(code, IOCTL_ATA_PASS_THROUGH)
        self.assertEqual(len(request), ctypes.sizeof(header))
        self.assertEqual(out_size, ctypes.sizeof(header) + 512)
        sent = AtaPassThrough.from_buffer_copy(request)
        self.assertEqual(sent.CurrentTaskFile[6], 0xEC)
        self.assertEqual(sent.AtaFlags, 0x03)  # only data-in, never data-out
        header.DataTransferLength = 0
        api.ioctl.return_value = bytes(header) + bytes(512)
        with self.assertRaises(ValueError):
            api.identify_ata("fake")

    def test_native_inspection_has_no_writefile_call_and_closes_handle(self):
        target = disk(simulated=False)
        fake = FakeApi(target)
        with patch("dejavu.windows_io.NativeApi", return_value=fake):
            info = inspect_disk(target.number)
        self.assertEqual(info["serial"], target.serial)
        self.assertEqual(fake.writes, 0)
        self.assertEqual(fake.closed, ["disk"])

    def test_volume_extents_detect_multi_disk_and_truncated_responses(self):
        data = struct.pack("<I4xI4xqqI4xqq", 2, 1, 0, 100, 2, 0, 100)
        self.assertEqual(volume_disk_numbers(data), {1, 2})
        for bad in (b"", bytes(7), struct.pack("<I4x", 0), data[:-1]):
            with self.assertRaises(ValueError):
                volume_disk_numbers(bad)

    @unittest.skipIf(os.name == "nt", "Controllo dedicato ai sistemi non Windows")
    def test_linux_cannot_initialize_real_disk_api(self):
        with self.assertRaises(RuntimeError):
            NativeApi()


class FakeApi:
    """No OS handles: models resource ownership and safety failures."""
    def __init__(self, target, lock_failure=False, write_failure=False, multi_volume=False,
                 actual_serial=None, lock_errors=None, dismount_failure=False):
        self.target = target
        self.lock_failure, self.write_failure = lock_failure, write_failure
        self.multi_volume, self.actual_serial = multi_volume, actual_serial
        self.lock_errors = list(lock_errors or [])
        self.dismount_failure = dismount_failure
        self.lock_attempts = 0
        self.controls = []
        self.closed = []
        self.writes = 0
        self.kernel = self
        self.buffer = ctypes.create_string_buffer(8 * 1024**2)

    def open(self, path, **kwargs):
        return "disk" if "PhysicalDrive" in path else "volume"

    def disk_info(self, handle):
        return {"number": self.target.number, "size": self.target.size,
                "sector_size": self.target.sector_size,
                "serial": self.actual_serial or self.target.serial, "kind": "HDD"}

    def ioctl(self, handle, code, *args, **kwargs):
        self.controls.append(code)
        if code == IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS:
            return struct.pack("<I4xI4xqq", 1, 99 if self.multi_volume else self.target.number, 0, self.target.size)
        if code == FSCTL_LOCK_VOLUME:
            self.lock_attempts += 1
            if self.lock_errors:
                raise self.lock_errors.pop(0)
            if self.lock_failure:
                raise OSError("Volume in uso")
        if code == FSCTL_DISMOUNT_VOLUME and self.dismount_failure:
            raise DeviceError("Smontaggio volume", 5, "Accesso negato")
        return b""

    def allocate(self, length):
        return ctypes.addressof(self.buffer)

    def free(self, pointer):
        pass

    def close(self, handle):
        self.closed.append(handle)

    def WriteFile(self, handle, pointer, length, count, overlapped):
        self.writes += 1
        return 0 if self.write_failure else 1

    def error(self, text):
        return OSError(text + ": errore simulato")


class RawSafetyTests(unittest.TestCase):
    def target(self):
        return disk(simulated=False, volume_paths=("\\\\?\\Volume{GUID}\\",))

    def test_volume_lock_failure_aborts_before_offline_or_write(self):
        target = self.target()
        fake = FakeApi(target, lock_failure=True)
        with patch("dejavu.windows_io.NativeApi", return_value=fake), patch("dejavu.inventory.powershell") as ps:
            with self.assertRaises(Blocked):
                with RawSession(target):
                    self.fail("Apertura non doveva riuscire")
        ps.assert_not_called()
        self.assertEqual(fake.writes, 0)
        self.assertIn("disk", fake.closed)
        self.assertIn("volume", fake.closed)

    def test_temporary_volume_lock_errors_retry_then_prepare_safely(self):
        target = self.target()
        fake = FakeApi(target, lock_errors=[DeviceError("Blocco volume", 5, "Accesso negato"),
                                            DeviceError("Blocco volume", 32, "Volume in uso")])
        def offline_command(command):
            self.assertEqual(fake.lock_attempts, 3)
            self.assertIn(FSCTL_DISMOUNT_VOLUME, fake.controls)
        with patch("dejavu.windows_io.NativeApi", return_value=fake), \
                patch("dejavu.inventory.powershell", side_effect=offline_command) as ps, \
                patch("dejavu.windows_io.time.sleep") as sleep:
            with RawSession(target):
                self.assertEqual(fake.writes, 0)
        self.assertEqual(ps.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(all(call.args == (LOCK_RETRY_DELAY,) for call in sleep.call_args_list))

    def test_persistent_access_denied_stops_before_dismount_offline_or_write(self):
        target = self.target()
        errors = [DeviceError("Blocco volume", 5, "Accesso negato") for _ in range(LOCK_ATTEMPTS)]
        fake = FakeApi(target, lock_errors=errors)
        with patch("dejavu.windows_io.NativeApi", return_value=fake), \
                patch("dejavu.inventory.powershell") as ps, \
                patch("dejavu.windows_io.time.sleep") as sleep:
            with self.assertRaisesRegex(Blocked, "Chiudi le finestre di Esplora file"):
                with RawSession(target):
                    self.fail("Volume ancora occupato")
        self.assertEqual(fake.lock_attempts, LOCK_ATTEMPTS)
        self.assertEqual(sleep.call_count, LOCK_ATTEMPTS - 1)
        self.assertNotIn(FSCTL_DISMOUNT_VOLUME, fake.controls)
        ps.assert_not_called()
        self.assertEqual(fake.writes, 0)
        self.assertIn("disk", fake.closed)
        self.assertIn("volume", fake.closed)

    def test_non_retryable_lock_error_stops_immediately(self):
        target = self.target()
        fake = FakeApi(target, lock_errors=[DeviceError("Blocco volume", 1, "Funzione non corretta")])
        with patch("dejavu.windows_io.NativeApi", return_value=fake), \
                patch("dejavu.inventory.powershell") as ps, \
                patch("dejavu.windows_io.time.sleep") as sleep:
            with self.assertRaisesRegex(Blocked, "WinError 1"):
                with RawSession(target):
                    self.fail("Controllo non supportato")
        self.assertEqual(fake.lock_attempts, 1)
        sleep.assert_not_called()
        ps.assert_not_called()
        self.assertEqual(fake.writes, 0)

    def test_dismount_failure_stops_before_offline_or_write(self):
        target = self.target()
        fake = FakeApi(target, dismount_failure=True)
        with patch("dejavu.windows_io.NativeApi", return_value=fake), \
                patch("dejavu.inventory.powershell") as ps:
            with self.assertRaisesRegex(Blocked, "Nessuna scrittura eseguita"):
                with RawSession(target):
                    self.fail("Smontaggio non riuscito")
        self.assertEqual(fake.lock_attempts, 1)
        ps.assert_not_called()
        self.assertEqual(fake.writes, 0)
        self.assertIn("disk", fake.closed)
        self.assertIn("volume", fake.closed)

    def test_native_identity_change_aborts_before_dismount(self):
        target = self.target()
        fake = FakeApi(target, actual_serial="ANOTHER-DISK")
        with patch("dejavu.windows_io.NativeApi", return_value=fake), patch("dejavu.inventory.powershell") as ps:
            with self.assertRaises(Blocked):
                with RawSession(target):
                    self.fail("Identità diversa")
        ps.assert_not_called()
        self.assertEqual(fake.writes, 0)

    def test_volume_on_other_physical_disk_is_blocked(self):
        target = self.target()
        fake = FakeApi(target, multi_volume=True)
        with patch("dejavu.windows_io.NativeApi", return_value=fake), patch("dejavu.inventory.powershell") as ps:
            with self.assertRaises(Blocked):
                with RawSession(target):
                    self.fail("Volume non corrispondente")
        ps.assert_not_called()

    def test_failed_raw_write_is_conservatively_left_offline(self):
        target = self.target()
        fake = FakeApi(target, write_failure=True)
        with patch("dejavu.windows_io.NativeApi", return_value=fake), patch("dejavu.inventory.powershell") as ps:
            session = RawSession(target)
            with self.assertRaises(OSError):
                with session:
                    session.write(bytes(512))
        self.assertTrue(session.wrote)
        self.assertEqual(ps.call_count, 1)
        self.assertIn("$true", ps.call_args.args[0])
        self.assertTrue(session.warnings)
        self.assertIn("disk", fake.closed)


if __name__ == "__main__":
    unittest.main()
