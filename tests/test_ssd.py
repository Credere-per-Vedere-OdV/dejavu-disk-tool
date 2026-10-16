"""SSD protocol and failure checks with simulated Windows APIs only."""
from dataclasses import replace
import ctypes as C
import json
from pathlib import Path
import struct
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from dejavu.core import Blocked, Disk, Inventory, run_job, validate_target
from dejavu.reports import save_reports
from dejavu.ssd import SsdSession, taskfile, sat_registers, sanitize_state, recover_security
from dejavu.windows_io import (AtaPassThrough, ScsiPassThroughDirect, ata_identity,
    IOCTL_ATA_PASS_THROUGH, IOCTL_SCSI_PASS_THROUGH_DIRECT, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS)


def target(method="ATA_SANITIZE_BLOCK"):
    return Disk(2, "SSD TEST", "SSD-SERIAL-2", "id2", 4096, 512, "SATA", "SSD",
                identity_source="ATA", firmware_model="SSD TEST", firmware_revision="1.0",
                native_methods=(method,))


def descriptor(flags=0, extended=True, error=0, status=0x40):
    d = bytes([9, 12, int(extended), error, flags, 0, 0, 0, 0, 0x80, 0, 0, 0x40, status])
    return bytes([0x72, 1, 0, 0x1D, 0, 0, 0, len(d)]) + d


class FakeNative:
    def __init__(self, disk):
        self.disk = disk
        self.commands, self.controls, self.opens, self.buffers = [], [], [], {}
        self.states = [0, 0x40, 0x80]
        self.fail = None
        self.deny_status = False
        self.security = ()
        self.changed_serial = None
        self.on_command = None

    def open(self, path, **options):
        self.opens.append((path, options))
        return "disk"

    def close(self, handle):
        pass

    def disk_info(self, handle):
        d = self.disk
        return dict(number=d.number, size=d.size, sector_size=d.sector_size,
                    serial=self.changed_serial or d.serial, kind="SSD", serial_source="ATA",
                    firmware_model=d.firmware_model, firmware_revision=d.firmware_revision,
                    native_methods=d.native_methods, security_state=self.security,
                    identify_transport="ATA")

    def allocate(self, length):
        b = C.create_string_buffer(length)
        pointer = C.addressof(b)
        self.buffers[pointer] = b
        return pointer

    def free(self, pointer):
        self.buffers.pop(pointer, None)

    def ioctl(self, handle, code, data=b"", out_size=0):
        self.controls.append(code)
        if code == IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS:
            return struct.pack("<I4xI4xqq", 1, self.disk.number, 0, self.disk.size)
        if code == IOCTL_SCSI_PASS_THROUGH_DIRECT:
            raise OSError("SAT non disponibile nella simulazione ATA")
        if code != IOCTL_ATA_PASS_THROUGH:
            return b""
        header = AtaPassThrough.from_buffer_copy(data[:C.sizeof(AtaPassThrough)])
        command, feature = header.CurrentTaskFile[6], header.CurrentTaskFile[0]
        payload = data[C.sizeof(header):]
        self.commands.append((command, feature, payload))
        if self.on_command:
            self.on_command(command, feature)
        if self.fail == (command, feature):
            raise OSError("Comando SSD rifiutato")
        flags = 0
        if command == 0xB4 and feature == 0:
            if self.deny_status:
                raise OSError("Stato Sanitize non disponibile")
            flags = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        if command == 0xF1:
            self.security = ("abilitata",)
        elif command in (0xF4, 0xF6):
            self.security = ()
        elif command == 0xF2:
            self.security = ("abilitata",)
        header.CurrentTaskFile[:] = (0, 0, 0, 0x80, 0, 0x40, 0x40, 0)
        header.PreviousTaskFile[1] = flags
        return bytes(header) + bytes(len(payload))


class ProtocolTests(unittest.TestCase):
    def test_identify_capabilities_and_invalid_words(self):
        b = bytearray(512)
        struct.pack_into("<H", b, 434, 1)
        struct.pack_into("<H", b, 118, 0x9000)
        struct.pack_into("<H", b, 256, 0x21)
        struct.pack_into("<H", b, 180, 10)
        i = ata_identity(bytes(b))
        self.assertEqual(i["native_methods"], ("ATA_SANITIZE_BLOCK", "ATA_SECURITY_ENHANCED"))
        self.assertEqual(i["enhanced_erase_minutes"], 20)
        struct.pack_into("<H", b, 118, 0xFFFF)
        struct.pack_into("<H", b, 256, 0xFFFF)
        self.assertEqual(ata_identity(bytes(b))["native_methods"], ())

    def test_security_state_bits(self):
        b = bytearray(512)
        struct.pack_into("<H", b, 256, 0x3F)
        self.assertEqual(ata_identity(bytes(b))["security_state"],
                         ("abilitata", "bloccata", "congelata", "tentativi esauriti"))

    def test_sat_requires_complete_successful_return_registers(self):
        self.assertEqual(sat_registers(2, descriptor(0x80))[7], 0x80)
        for status, sense in [(0, b""), (2, descriptor()[:-1]), (8, descriptor()),
                              (2, b"\x70" + descriptor()[1:])]:
            with self.subTest(status=status, sense=sense), self.assertRaises(OSError):
                sat_registers(status, sense)

    def test_sanitize_progress_and_completion(self):
        self.assertEqual(sanitize_state(sat_registers(2, descriptor(0x40))), ("RUNNING", 50))
        self.assertEqual(sanitize_state(sat_registers(2, descriptor(0x80))), ("SUCCESS", 100))
        self.assertEqual(sanitize_state(sat_registers(2, descriptor(0))), ("NEVER", 0))

    def test_frozen_and_unknown_sanitize_status(self):
        with self.assertRaises(Blocked):
            sanitize_state(sat_registers(2, descriptor(0x20)))
        for flags in (1, 0x10, 0xC0):
            with self.subTest(flags=flags), self.assertRaises(OSError):
                sanitize_state(sat_registers(2, descriptor(flags)))

    def test_command_allowlist_parameters_and_enhanced_only(self):
        api = FakeNative(target())
        for kwargs in [dict(command=0xF5), dict(command=0xF1),
                       dict(command=0xF4, data=bytes(512)),
                       dict(command=0xB4, extended=True, feature=0x12, lba=0),
                       dict(command=0xB4, extended=False)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                taskfile(api, "disk", "ATA", **kwargs)
        self.assertEqual(api.commands, [])

    def test_ata_48bit_signature_and_output_payload(self):
        api = FakeNative(target())
        saved = api.ioctl
        headers = []
        def capture(handle, code, data, size):
            headers.append(AtaPassThrough.from_buffer_copy(data))
            return saved(handle, code, data, size)
        api.ioctl = capture
        taskfile(api, "disk", "ATA", 0xB4, 0x12, 0x426B4572, True)
        h = headers[0]
        self.assertEqual(h.AtaFlags, 0x11)
        self.assertEqual(list(h.CurrentTaskFile)[2:5], [0x72, 0x45, 0x6B])
        self.assertEqual(h.PreviousTaskFile[2], 0x42)
        taskfile(api, "disk", "ATA", 0xF1, data=b"\x00\x00" + b"P" * 510)
        self.assertEqual(headers[1].AtaFlags, 5)
        self.assertEqual(headers[1].DataTransferLength, 512)

    def test_sat_cdb_output_direction_and_extend_proof(self):
        api = FakeNative(target())
        headers = []
        def sat(handle, code, data, size):
            self.assertEqual(code, IOCTL_SCSI_PASS_THROUGH_DIRECT)
            h = ScsiPassThroughDirect.from_buffer_copy(data)
            headers.append(h)
            sense = descriptor(0x80, extended=bool(h.Cdb[1] & 1))
            h.ScsiStatus, h.SenseInfoLength = 2, len(sense)
            return bytes(h) + sense + bytes(32 - len(sense))
        api.ioctl = sat
        taskfile(api, "disk", "SAT-16", 0xB4, 0x12, 0x426B4572, True)
        self.assertEqual(list(headers[0].Cdb), [0x85, 7, 0x20, 0, 0x12, 0, 0, 0x42, 0x72, 0, 0x45, 0, 0x6B, 0x40, 0xB4, 0])
        taskfile(api, "disk", "SAT-16", 0xF1, data=bytes(512))
        self.assertEqual(headers[1].DataIn, 0)
        self.assertEqual(list(headers[1].Cdb)[:3], [0x85, 10, 0x26])
        self.assertEqual(api.buffers, {})

    def test_sat_rejects_ata_error_or_missing_extend(self):
        api = FakeNative(target())
        for sense in (descriptor(error=4), descriptor(status=0x41), descriptor(extended=False)):
            def sat(handle, code, data, size):
                h = ScsiPassThroughDirect.from_buffer_copy(data)
                h.ScsiStatus, h.SenseInfoLength = 2, len(sense)
                return bytes(h) + sense + bytes(32-len(sense))
            api.ioctl = sat
            with self.subTest(sense=sense), self.assertRaises(OSError):
                taskfile(api, "disk", "SAT-16", 0xB4, extended=True)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def run_ssd(self, d=None, api=None, cancel=None):
        d = d or target()
        api = api or FakeNative(d)
        events = []
        with patch("dejavu.windows_io.NativeApi", return_value=api), \
             patch("dejavu.inventory.powershell"), patch("dejavu.ssd.time.sleep"), \
             patch("dejavu.ssd.protect_password", return_value=b"ENCRYPTED-RECORD"):
            result = run_job(d, lambda: Inventory((d,), True),
                             lambda disk: SsdSession(disk, self.folder), cancel or Event(), events.append)
        return result, api, events

    def test_eligible_sata_and_unsupported_nvme_or_method(self):
        d = target()
        self.assertEqual(validate_target(d, Inventory((d,), True)), d)
        for invalid in (replace(d, bus="NVMe"), replace(d, native_methods=()),
                        replace(d, identity_source="WINDOWS")):
            with self.subTest(invalid=invalid), self.assertRaises(Blocked):
                validate_target(invalid, Inventory((invalid,), True))

    def test_protected_and_duplicate_serial_ssd_do_not_open(self):
        for d, fresh in [(replace(target(), protected_reasons=("Windows",)), None),
                         (target(), Inventory((target(), replace(target(), number=3)), True))]:
            opens = []
            inventory = fresh or Inventory((d,), True)
            r = run_job(d, lambda: inventory, opens.append, Event(), lambda e: None)
            self.assertEqual(r.status, "BLOCKED")
            self.assertEqual(opens, [])

    def test_block_erase_success_has_native_completion_no_host_counts(self):
        r, api, events = self.run_ssd()
        self.assertEqual(r.status, "SUCCESS")
        self.assertEqual(r.native_details["completion"], "device_confirmed")
        self.assertIsNone(r.written)
        self.assertIsNone(r.verified)
        self.assertFalse(api.opens[0][1]["unbuffered"])
        self.assertEqual(api.buffers, {})
        self.assertEqual(sum(c[:2] == (0xB4, 0x12) for c in api.commands), 1)
        self.assertTrue(any(e.get("native") for e in events))

    def test_sanitize_status_denied_never_sends_erase(self):
        api = FakeNative(target()); api.deny_status = True
        r, api, _ = self.run_ssd(api=api)
        self.assertEqual(r.status, "BLOCKED")
        self.assertFalse(any(c[1] == 0x12 for c in api.commands))

    def test_frozen_preflight_never_sends_erase(self):
        api = FakeNative(target()); api.states = [0x20]
        r, api, _ = self.run_ssd(api=api)
        self.assertEqual(r.status, "BLOCKED")
        self.assertEqual(len(api.commands), 1)

    def test_already_running_preflight_never_sends_erase(self):
        api = FakeNative(target()); api.states = [0x40]
        r, api, _ = self.run_ssd(api=api)
        self.assertEqual(r.status, "BLOCKED")
        self.assertEqual(len(api.commands), 1)

    def test_changed_open_identity_sends_no_command(self):
        api = FakeNative(target()); api.changed_serial = "OTHER"
        r, api, _ = self.run_ssd(api=api)
        self.assertEqual(r.status, "BLOCKED")
        self.assertEqual(api.commands, [])

    def test_failed_submission_cannot_reuse_old_success(self):
        api = FakeNative(target()); api.states = [0x80]; api.fail = (0xB4, 0x12)
        r, _, _ = self.run_ssd(api=api)
        self.assertEqual(r.status, "FAILED")
        self.assertEqual(r.native_details["completion"], "unconfirmed")

    def test_frozen_status_after_start_is_failed_not_unstarted(self):
        api = FakeNative(target()); api.states = [0, 0x20]
        r, _, _ = self.run_ssd(api=api)
        self.assertEqual(r.status, "FAILED")

    def test_cancel_before_start_sends_nothing(self):
        cancel = Event(); cancel.set()
        r, api, _ = self.run_ssd(cancel=cancel)
        self.assertEqual(r.status, "CANCELLED")
        self.assertEqual(api.commands, [])

    def test_cancel_after_start_tracks_device_to_success(self):
        cancel = Event(); api = FakeNative(target())
        api.on_command = lambda cmd, feat: cancel.set() if (cmd, feat) == (0xB4, 0x12) else None
        r, _, _ = self.run_ssd(api=api, cancel=cancel)
        self.assertEqual(r.status, "SUCCESS")
        self.assertTrue(r.warnings)

    def test_enhanced_erase_uses_password_prepare_and_enhanced_command(self):
        d = target("ATA_SECURITY_ENHANCED")
        r, api, _ = self.run_ssd(d)
        self.assertEqual(r.status, "SUCCESS")
        self.assertEqual([c[0] for c in api.commands], [0xF1, 0xF3, 0xF4])
        self.assertEqual(api.commands[-1][2][:2], b"\x02\x00")
        self.assertEqual(api.commands[0][2][2:34], api.commands[-1][2][2:34])
        self.assertEqual(list(self.folder.glob('SSD-*.json')), [])

    def test_enhanced_failure_keeps_only_encrypted_recovery_record(self):
        d = target("ATA_SECURITY_ENHANCED"); api = FakeNative(d); api.fail = (0xF4, 0)
        r, _, _ = self.run_ssd(d, api)
        self.assertEqual(r.status, "FAILED")
        records = list(self.folder.glob('SSD-*.json'))
        self.assertEqual(len(records), 1)
        self.assertNotIn(api.commands[0][2][2:34].decode('ascii'), records[0].read_text())
        self.assertTrue(any('profilo Windows' in warning for warning in r.warnings))

    def test_dpapi_failure_occurs_before_setting_password(self):
        d = target("ATA_SECURITY_ENHANCED"); api = FakeNative(d)
        with patch("dejavu.windows_io.NativeApi", return_value=api), \
             patch("dejavu.inventory.powershell"), \
             patch("dejavu.ssd.protect_password", side_effect=OSError("DPAPI unavailable")):
            r = run_job(d, lambda: Inventory((d,), True), lambda disk: SsdSession(disk, self.folder), Event(), lambda e: None)
        self.assertEqual(r.status, "FAILED")
        self.assertEqual(api.commands, [])

    def test_report_has_native_verification_and_null_counts(self):
        r, _, _ = self.run_ssd()
        html, data = save_reports(self.folder, Inventory((r.disk,), True), [r], 1)
        self.assertIn('ESITO DEL DISPOSITIVO CONFERMATO', html.read_text())
        self.assertIsNone(json.loads(data.read_text())["results"][0]["written"])

    def test_recovery_removes_own_password_without_any_erase_command(self):
        d = target("ATA_SECURITY_ENHANCED"); api = FakeNative(d); api.security = ("abilitata", "bloccata")
        record = self.folder/'key.json'
        record.write_text(json.dumps(dict(serial=d.serial, model=d.firmware_model, firmware=d.firmware_revision,
                                          owner_pid=1234, password_dpapi='RU5DUllQVEVE')))
        with patch("dejavu.windows_io.NativeApi", return_value=api), patch("dejavu.inventory.powershell"), \
             patch("dejavu.ssd.recovery_owner_running", return_value=False), \
             patch("dejavu.ssd.protect_password", return_value=b'P'*32):
            message = recover_security(d, Inventory((d,), True), record, d.serial)
        self.assertEqual([c[0] for c in api.commands], [0xF2, 0xF6])
        self.assertIn('non attesta', message)
        self.assertFalse(record.exists())

    def test_recovery_wrong_disk_or_live_owner_never_opens_device(self):
        d = target(); record = self.folder/'key.json'
        payload = dict(serial=d.serial, model=d.firmware_model, firmware=d.firmware_revision,
                       owner_pid=1234, password_dpapi='RU5DUllQVEVE')
        for serial, active in [('OTHER', False), (d.serial, True)]:
            record.write_text(json.dumps({**payload, 'serial': serial}))
            with patch("dejavu.windows_io.NativeApi") as native, \
                 patch("dejavu.ssd.recovery_owner_running", return_value=active), self.assertRaises(Blocked):
                recover_security(d, Inventory((d,), True), record, d.serial)
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
