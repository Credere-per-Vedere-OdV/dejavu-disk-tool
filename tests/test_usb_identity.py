"""USB identity regressions. All device queries are faked; no raw disk I/O."""
import ctypes as C
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch

from dejavu.core import Blocked, Disk, Inventory, validate_target
from dejavu.diagnostics import build_payload
from dejavu.inventory import WindowsInventory
from dejavu.windows_io import (NativeApi, RawSession, ata_identity, sat_identify_ok,
                               ScsiPassThroughDirect, IOCTL_STORAGE_GET_DEVICE_NUMBER,
                               IOCTL_DISK_GET_LENGTH_INFO, IOCTL_DISK_GET_DRIVE_GEOMETRY,
                               IOCTL_STORAGE_QUERY_PROPERTY, IOCTL_SCSI_PASS_THROUGH_DIRECT)


def ata_data(serial="WD-REAL-001", model="WDC WD5000LPLX-08ZNTT0", rate=7200):
    result = bytearray(512)
    for offset, length, text in ((20, 20, serial), (54, 40, model)):
        value = text.encode("ascii").ljust(length)
        result[offset:offset + length] = b"".join(value[index:index + 2][::-1] for index in range(0, length, 2))
    struct.pack_into("<H", result, 434, rate)
    return bytes(result)


def windows_payload():
    rows = []
    for number, model, serial, bus, kind, protected in (
            (0, "Windows", "SYS", "NVMe", "SSD", ["Windows in esecuzione"]),
            (1, "WDC WD50 00LPLX-08ZNTT0", "1234567890127", "USB", "UNKNOWN", []),
            (2, "ST500DM0 02-1BD142", "1234567890127", "USB", "UNKNOWN", [])):
        rows.append(dict(Number=number, Model=model, Serial=serial, UniqueId=f"USB-SLOT-{number}",
                         Size=12288, SectorSize=512, Bus=bus, Kind=kind, Protected=protected,
                         Volumes=[], ReadOnly=False, Offline=False))
    return dict(ProtectionOK=True, Disks=rows)


def native_info(number, serial, model, kind="HDD"):
    return dict(number=number, size=12288, sector_size=512, serial=serial, kind=kind,
                evidence="SAT-16 IDENTIFY, rotation rate", transport_serial="1234567890127",
                serial_source="ATA", firmware_model=model, bus_type=7,
                probe_notes=("SAT-16 IDENTIFY disponibile.",))


class UsbIdentityTests(unittest.TestCase):
    def scan(self, info, payload=None):
        def probe(number):
            value = info[number]
            if isinstance(value, Exception):
                raise value
            return value
        with patch("dejavu.inventory.powershell", return_value=json.dumps(payload or windows_payload())), \
             patch("dejavu.windows_io.inspect_disk", side_effect=probe) as inspect:
            result = WindowsInventory(Path("."), Path(".")).scan()
        self.assertEqual([call.args[0] for call in inspect.call_args_list], [1, 2])
        return result

    def good_info(self):
        return {1:native_info(1,"WD-REAL-001","WDC WD5000LPLX-08ZNTT0"),
                2:native_info(2,"SEAGATE-REAL-002","ST500DM002-1BD142")}

    def bridge_case(self):
        """Anonymous reproduction of a dual Sabrent bridge's metadata shape."""
        payload = windows_payload()
        info = {}
        for number in (1, 2):
            payload["Disks"][number].update(
                Model="Sabrent Dual SATA Bridge", Serial="00000000000000000000",
                UniqueId="5000000000000001", Size=128035676160)
            info[number] = native_info(number, f"TEST-SSD-{number}",
                                       "Samsung SSD 850 PRO 128GB", "SSD")
            info[number].update(size=128035676160,
                                transport_serial="00000000000000000000",
                                firmware_revision=f"TEST-FIRMWARE-{number}",
                                native_methods=("ATA_SECURITY_ENHANCED",),
                                security_state=(), identify_transport="SAT-16")
        return payload, info

    def test_generic_dual_bridge_uses_distinct_ssd_firmware_identities(self):
        payload, info = self.bridge_case()
        inventory = self.scan(info, payload)
        for target in inventory.disks[1:]:
            self.assertEqual(target.kind, "SSD")
            self.assertEqual(target.model, "Samsung SSD 850 PRO 128GB")
            self.assertEqual(target.serial, f"TEST-SSD-{target.number}")
            self.assertEqual(target.firmware_serial, target.serial)
            self.assertEqual(target.transport_model, "Sabrent Dual SATA Bridge")
            self.assertEqual(target.transport_serial, "00000000000000000000")
            self.assertEqual(target.identity_source, "ATA")
            self.assertEqual(target.identify_transport, "SAT-16")
            self.assertEqual(validate_target(target, inventory), target)
        self.assertTrue(inventory.disks[0].protected)
        with self.assertRaises(Blocked):
            validate_target(inventory.disks[0], inventory)

    def test_generic_bridge_does_not_authorize_duplicate_firmware_serials(self):
        payload, info = self.bridge_case()
        info[2]["serial"] = info[1]["serial"]
        inventory = self.scan(info, payload)
        for target in inventory.disks[1:]:
            with self.assertRaisesRegex(Blocked, "duplicato"):
                validate_target(target, inventory)

    def test_generic_bridge_missing_identity_or_capability_stays_blocked(self):
        for change in ({"serial":""}, {"serial":"00000000000000000000"},
                       {"firmware_model":""}, {"bus_type":11},
                       {"kind":"UNKNOWN"}, {"native_methods":()},
                       {"security_state":("congelata",)}, {"serial_source":"DESCRIPTOR"}):
            with self.subTest(change=change):
                payload, info = self.bridge_case()
                info[1].update(change)
                inventory = self.scan(info, payload)
                with self.assertRaises(Blocked):
                    validate_target(inventory.disks[1], inventory)

    def test_generic_bridge_wrong_handle_geometry_stays_blocked(self):
        for change in ({"number":2}, {"size":64000000000}, {"sector_size":4096}):
            with self.subTest(change=change):
                payload, info = self.bridge_case()
                info[1].update(change)
                inventory = self.scan(info, payload)
                with self.assertRaises(Blocked):
                    validate_target(inventory.disks[1], inventory)

    def test_generic_bridge_new_serial_invalidates_selection_and_open_handle(self):
        from dejavu.ssd import SsdSession
        payload, info = self.bridge_case()
        before = self.scan(info, payload)
        info[1]["serial"] = "REPLACEMENT-SSD"
        after = self.scan(info, payload)
        with self.assertRaisesRegex(Blocked, "cambiato"):
            validate_target(before.disks[1], after)
        fake = Mock()
        fake.disk_info.return_value = info[1]
        with patch("dejavu.windows_io.NativeApi", return_value=fake):
            session = SsdSession(before.disks[1], Path("unused-recovery"))
            session.handle = "fake"
            with self.assertRaisesRegex(Blocked, "serie"):
                session._assert_identity()
        fake.ioctl.assert_not_called()

    def test_all_zero_serial_is_blocked_even_for_a_single_target(self):
        target = Disk(1, "SSD", "00000000000000000000", "ID", 4096, 512, "USB", "SSD",
                      identity_source="ATA", firmware_model="SSD",
                      native_methods=("ATA_SECURITY_ENHANCED",))
        with self.assertRaisesRegex(Blocked, "serie"):
            validate_target(target, Inventory((target,), True))

    def test_distinct_firmware_serials_resolve_shared_usb_serial(self):
        inventory = self.scan(self.good_info())
        for target in inventory.disks[1:]:
            self.assertEqual(target.kind, "HDD")
            self.assertEqual(target.identity_source, "ATA")
            self.assertEqual(target.transport_serial, "1234567890127")
            self.assertNotEqual(target.serial, target.transport_serial)
            self.assertEqual(validate_target(target, inventory), target)
        self.assertNotEqual(inventory.disks[1].serial, inventory.disks[2].serial)
        self.assertTrue(inventory.disks[0].protected)

    def test_two_slots_returning_same_firmware_serial_stay_blocked(self):
        values = self.good_info()
        values[2]["serial"] = values[1]["serial"]
        inventory = self.scan(values)
        for target in inventory.disks[1:]:
            with self.assertRaisesRegex(Blocked, "duplicato"):
                validate_target(target, inventory)

    def test_wrong_firmware_model_is_not_assigned_to_other_usb_slot(self):
        values = self.good_info()
        values[2] = native_info(2,"WD-REAL-001","WDC WD5000LPLX-08ZNTT0")
        inventory = self.scan(values)
        self.assertEqual(inventory.disks[2].kind, "UNKNOWN")
        self.assertEqual(inventory.disks[2].serial, "1234567890127")
        with self.assertRaises(Blocked):
            validate_target(inventory.disks[2], inventory)

    def test_no_firmware_identity_cannot_use_unique_slot_ids_as_override(self):
        values = {n:dict(number=n,size=12288,sector_size=512,serial="1234567890127",
                         serial_source="DESCRIPTOR",kind="UNKNOWN",evidence="",
                         probe_notes=("SAT non disponibile",)) for n in (1,2)}
        inventory = self.scan(values)
        for target in inventory.disks[1:]:
            self.assertEqual(target.kind, "UNKNOWN")
            with self.assertRaises(Blocked):
                validate_target(target, inventory)

    def test_probe_failure_has_readable_diagnostic_notes(self):
        values = self.good_info()
        values[1] = OSError("DeviceIoControl 0x4D014: accesso negato")
        inventory = self.scan(values)
        self.assertEqual(inventory.disks[1].kind, "UNKNOWN")
        self.assertIn("accesso negato", inventory.disks[1].probe_notes[0])

    def test_ssd_firmware_remains_blocked(self):
        values = self.good_info()
        values[1]["kind"] = "SSD"
        inventory = self.scan(values)
        self.assertEqual(inventory.disks[1].kind, "SSD")
        with self.assertRaisesRegex(Blocked, "SSD"):
            validate_target(inventory.disks[1], inventory)

    def test_changed_firmware_serial_invalidates_old_selection(self):
        before = self.scan(self.good_info())
        values = self.good_info()
        values[1]["serial"] = "REPLACEMENT"
        after = self.scan(values)
        with self.assertRaisesRegex(Blocked, "cambiato"):
            validate_target(before.disks[1], after)

    def test_firmware_claim_on_non_usb_native_bus_is_not_trusted(self):
        values = self.good_info()
        values[1]["bus_type"] = 11
        inventory = self.scan(values)
        self.assertEqual(inventory.disks[1].kind, "UNKNOWN")

    def test_real_usb_hdd_with_only_transport_identity_is_blocked(self):
        target=Disk(1,"HDD","TRANSPORT","SLOT-ID",12288,512,"USB",kind="HDD",
                    identity_source="WINDOWS",simulated=False)
        with self.assertRaisesRegex(Blocked,"IDENTIFY"):
            validate_target(target,Inventory((target,),True))

    def test_raw_session_requires_selected_firmware_identity_to_remain_available(self):
        inventory = self.scan(self.good_info())
        target = inventory.disks[1]
        for change in ({"serial_source":"DESCRIPTOR"}, {"kind":"UNKNOWN"},
                       {"firmware_model":"ANOTHER MODEL"}, {"serial":"REPLACEMENT"}):
            value = native_info(1, target.serial, target.firmware_model)
            value.update(change)
            fake = Mock()
            fake.disk_info.return_value = value
            with patch("dejavu.windows_io.NativeApi", return_value=fake):
                session = RawSession(target)
                session.handle = "fake"
                with self.assertRaises(Blocked):
                    session._assert_identity()


class NativeUsbProbeTests(unittest.TestCase):
    def api(self, bus=7):
        api = object.__new__(NativeApi)
        def ioctl(handle, code, data=b"", out_size=0):
            if code == IOCTL_STORAGE_GET_DEVICE_NUMBER:
                return struct.pack("<III",7,1,0xFFFFFFFF)
            if code == IOCTL_DISK_GET_LENGTH_INFO:
                return struct.pack("<q",12288)
            if code == IOCTL_DISK_GET_DRIVE_GEOMETRY:
                return struct.pack("<qIIII",1,0,1,1,512)
            if code == IOCTL_STORAGE_QUERY_PROPERTY:
                prop=struct.unpack_from("<I",data)[0]
                if prop==0:
                    result=bytearray(64)
                    struct.pack_into("<I",result,24,36)
                    struct.pack_into("<I",result,28,bus)
                    result[36:50]=b"1234567890127\x00"
                    return bytes(result)
                raise OSError("Property non disponibile")
            raise AssertionError(code)
        api.ioctl=Mock(side_effect=ioctl)
        api.identify_ata=Mock(side_effect=OSError("ATA non supportato tramite USB"))
        api.identify_sat=Mock(side_effect=lambda handle,length:ata_data())
        return api

    def test_usb_descriptor_and_firmware_serial_are_kept_separate(self):
        result=self.api().disk_info("fake")
        self.assertEqual(result["serial"],"WD-REAL-001")
        self.assertEqual(result["transport_serial"],"1234567890127")
        self.assertEqual(result["serial_source"],"ATA")
        self.assertEqual(result["kind"],"HDD")

    def test_non_usb_serial_conflict_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError,"conflitto"):
            self.api(bus=11).disk_info("fake")

    def test_sat12_is_tried_after_sat16_failure(self):
        api=self.api()
        api.identify_sat.side_effect=lambda handle,length: (_ for _ in ()).throw(OSError("SAT16 non supportato")) if length==16 else ata_data()
        result=api.disk_info("fake")
        self.assertEqual([c.args[1] for c in api.identify_sat.call_args_list],[16,12])
        self.assertEqual(result["serial"],"WD-REAL-001")
        self.assertIn("SAT-12",result["evidence"])

    def test_empty_ata_response_does_not_claim_hdd_or_firmware_identity(self):
        api=self.api()
        api.identify_sat.side_effect=lambda handle,length:bytes(512)
        result=api.disk_info("fake")
        self.assertEqual(result["kind"],"UNKNOWN")
        self.assertEqual(result["serial_source"],"DESCRIPTOR")
        self.assertTrue(any("senza modello" in note for note in result["probe_notes"]))

    def test_all_zero_firmware_serial_is_not_a_valid_identify_response(self):
        api = self.api()
        api.identify_sat.side_effect = lambda handle,length: ata_data(serial="00000000000000000000")
        result = api.disk_info("fake")
        self.assertEqual(result["kind"], "UNKNOWN")
        self.assertEqual(result["serial_source"], "DESCRIPTOR")

    def test_invalid_identify_checksum_is_rejected(self):
        data=bytearray(ata_data())
        data[510]=0xA5
        data[511]=(-sum(data))%256
        self.assertEqual(ata_identity(bytes(data))["serial"],"WD-REAL-001")
        data[200]^=1
        with self.assertRaisesRegex(ValueError,"Checksum"):
            ata_identity(bytes(data))

    def test_sat_variants_issue_only_data_in_identify(self):
        for length in (12,16):
            api=object.__new__(NativeApi)
            buffer=C.create_string_buffer(512)
            api.allocate=Mock(return_value=C.addressof(buffer))
            api.free=Mock()
            def ioctl(handle,code,request,out_size):
                self.assertEqual(code,IOCTL_SCSI_PASS_THROUGH_DIRECT)
                header=ScsiPassThroughDirect.from_buffer_copy(request)
                self.assertEqual(header.CdbLength,length)
                self.assertEqual(header.DataIn,1)
                self.assertEqual(header.Cdb[0],0x85 if length==16 else 0xA1)
                self.assertEqual(header.Cdb[14 if length==16 else 9],0xEC)
                self.assertEqual(header.Cdb[6 if length==16 else 4],1)
                self.assertEqual(header.Cdb[2],0x0E)
                C.memmove(header.DataBuffer,ata_data(),512)
                header.ScsiStatus=0
                return bytes(header)+bytes(32)
            api.ioctl=Mock(side_effect=ioctl)
            self.assertEqual(ata_identity(api.identify_sat("fake",length))["serial"],"WD-REAL-001")
            api.free.assert_called_once()

    def test_sat_check_condition_accepts_only_success_descriptor(self):
        sense=bytearray(22)
        sense[0]=0x72
        sense[1]=1
        sense[3]=0x1D
        sense[7]=14
        sense[8]=9
        sense[9]=12
        sense[21]=0x50
        self.assertTrue(sat_identify_ok(2,bytes(sense)))
        for change in ((21,0x51),(21,0x80),(21,0x00),(11,1),(1,5),(7,30),(9,20)):
            bad=bytearray(sense)
            bad[change[0]]=change[1]
            self.assertFalse(sat_identify_ok(2,bytes(bad)))
        self.assertFalse(sat_identify_ok(2,b""))
        self.assertFalse(sat_identify_ok(8,bytes(sense)))

    def test_short_sat_data_and_error_status_are_rejected(self):
        for count,status in ((0,0),(511,0),(512,2)):
            api=object.__new__(NativeApi)
            buffer=C.create_string_buffer(512)
            api.allocate=Mock(return_value=C.addressof(buffer))
            api.free=Mock()
            def ioctl(handle,code,request,out_size):
                header=ScsiPassThroughDirect.from_buffer_copy(request)
                header.DataTransferLength=count
                header.ScsiStatus=status
                return bytes(header)+bytes(32)
            api.ioctl=Mock(side_effect=ioctl)
            with self.assertRaises(ValueError):
                api.identify_sat("fake")
            api.free.assert_called_once()


class DiagnosticsTests(unittest.TestCase):
    def test_demo_diagnostics_cannot_query_real_windows_devices(self):
        with patch("dejavu.diagnostics.powershell") as ps:
            result=build_payload(Inventory((),True,simulated=True))
        ps.assert_not_called()
        self.assertTrue(result["simulated"])
        self.assertIn("version",result)

    def test_optional_pnp_failure_does_not_remove_inventory_or_probe_error(self):
        disk=Disk(1,"Test","SERIAL","ID",12288,512,"USB",probe_notes=("SAT errore",))
        with patch("dejavu.diagnostics.powershell",side_effect=RuntimeError("PnP non disponibile")):
            result=build_payload(Inventory((disk,),True))
        self.assertIn("PnP",result["windows_devices_error"])
        self.assertEqual(result["disks"][0]["probe_notes"],("SAT errore",))


if __name__=="__main__":
    unittest.main()
