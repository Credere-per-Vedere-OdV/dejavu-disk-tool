"""Windows raw-disk I/O. Never initialized on non-Windows platforms.

The overwrite writer is restricted to HDDs. Native SSD operations use a
separate session. Real hardware validation is still needed.
"""
from __future__ import annotations

import ctypes as C
import os
import struct
import time

from .core import Blocked, Disk, norm

U8, U16, U32, U64 = C.c_uint8, C.c_uint16, C.c_uint32, C.c_uint64
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_DISK_GET_DRIVE_GEOMETRY = 0x00070000
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
IOCTL_ATA_PASS_THROUGH = 0x0004D02C
IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x0004D014
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_UNLOCK_VOLUME = 0x0009001C
FSCTL_DISMOUNT_VOLUME = 0x00090020
LOCK_ATTEMPTS = 20
LOCK_RETRY_DELAY = 0.25


class DeviceError(OSError):
    """Keep the native error code so only temporary lock errors are retried."""
    def __init__(self, operation: str, winerror: int, description: str):
        super().__init__(f"{operation}: [WinError {winerror}] {description}")
        self.winerror = winerror


class AtaPassThrough(C.Structure):
    _fields_ = [("Length", U16), ("AtaFlags", U16), ("PathId", U8),
                ("TargetId", U8), ("Lun", U8), ("ReservedAsUchar", U8),
                ("DataTransferLength", U32), ("TimeOutValue", U32),
                ("ReservedAsUlong", U32), ("DataBufferOffset", C.c_size_t),
                ("PreviousTaskFile", U8 * 8), ("CurrentTaskFile", U8 * 8)]


class ScsiPassThroughDirect(C.Structure):
    _fields_ = [("Length", U16), ("ScsiStatus", U8), ("PathId", U8),
                ("TargetId", U8), ("Lun", U8), ("CdbLength", U8),
                ("SenseInfoLength", U8), ("DataIn", U8),
                ("DataTransferLength", U32), ("TimeOutValue", U32),
                ("DataBuffer", C.c_void_p), ("SenseInfoOffset", U32),
                ("Cdb", U8 * 16)]


def ata_identity(data: bytes) -> dict:
    if len(data) != 512:
        raise ValueError("Risposta ATA IDENTIFY incompleta.")
    raw = data[20:40]
    swapped = b"".join(raw[index:index + 2][::-1] for index in range(0, 20, 2))
    serial = swapped.decode("ascii", errors="replace").strip(" \x00")
    raw_model = data[54:94]
    model = b"".join(raw_model[index:index + 2][::-1] for index in range(0, 40, 2)).decode("ascii", "replace").strip(" \x00")
    if data[510] == 0xA5 and sum(data) % 256:
        raise ValueError("Checksum della risposta ATA IDENTIFY non valido.")
    rate = struct.unpack_from("<H", data, 217 * 2)[0]
    kind = "SSD" if rate == 1 else "HDD" if 0x401 <= rate <= 0xFFFE else "UNKNOWN"
    raw_revision = data[46:54]
    revision = b"".join(raw_revision[i:i + 2][::-1] for i in range(0, 8, 2)).decode("ascii", "replace").strip(" \x00")
    sanitize, security, minutes = struct.unpack_from("<H", data, 118)[0], struct.unpack_from("<H", data, 256)[0], struct.unpack_from("<H", data, 180)[0] & 0x7FFF
    methods, state = [], []
    if sanitize not in (0, 0xFFFF) and sanitize & 0x9000 == 0x9000:
        methods.append("ATA_SANITIZE_BLOCK")
    if security not in (0, 0xFFFF) and security & 0x21 == 0x21:
        methods.append("ATA_SECURITY_ENHANCED")
    if security == 0xFFFF:
        state.append("stato non valido")
    else:
        for bit, label in ((1, "abilitata"), (2, "bloccata"), (3, "congelata"), (4, "tentativi esauriti")):
            if security & (1 << bit):
                state.append(label)
    return {"serial": serial, "model": model, "kind": kind, "rotation_rate": rate,
            "firmware_revision": revision, "native_methods": tuple(methods),
            "security_state": tuple(state), "enhanced_erase_minutes": 2 * minutes if 0 < minutes < 255 else 0}


def sat_identify_ok(status: int, sense: bytes) -> bool:
    """Accept GOOD or a precise, successful ATA return descriptor only."""
    if status == 0:
        return True
    if status != 2 or len(sense) < 8 or sense[0] & 0x7F not in (0x72, 0x73):
        return False
    if sense[1] & 0x0F not in (0, 1) or sense[2:4] != b"\x00\x1D":
        return False
    end = 8 + sense[7]
    if end > len(sense):
        return False
    position = 8
    while position + 2 <= end:
        length = sense[position + 1] + 2
        if position + length > end:
            return False
        descriptor = sense[position:position + length]
        if descriptor[0] == 9:
            return (len(descriptor) >= 14 and descriptor[3] == 0
                    and descriptor[13] & 0xA9 == 0 and descriptor[13] & 0x40 != 0)
        position += length
    return False


def volume_disk_numbers(data: bytes) -> set[int]:
    if len(data) < 8:
        raise ValueError("Mappatura del volume incompleta.")
    count = struct.unpack_from("<I", data)[0]
    if count <= 0 or count > 128 or len(data) < 8 + count * 24:
        raise ValueError("Estensioni del volume non valide o incomplete.")
    return {struct.unpack_from("<I", data, 8 + index * 24)[0] for index in range(count)}


class NativeApi:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Accesso ai dischi reali disponibile soltanto su Windows.")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        k = self.kernel
        k.CreateFileW.argtypes = [C.c_wchar_p, U32, U32, C.c_void_p, U32, U32, C.c_void_p]
        k.CreateFileW.restype = C.c_void_p
        k.CloseHandle.argtypes = [C.c_void_p]
        k.CloseHandle.restype = C.c_int
        k.DeviceIoControl.argtypes = [C.c_void_p, U32, C.c_void_p, U32,
                                      C.c_void_p, U32, C.POINTER(U32), C.c_void_p]
        k.DeviceIoControl.restype = C.c_int
        k.ReadFile.argtypes = [C.c_void_p, C.c_void_p, U32, C.POINTER(U32), C.c_void_p]
        k.ReadFile.restype = C.c_int
        k.WriteFile.argtypes = k.ReadFile.argtypes
        k.WriteFile.restype = C.c_int
        k.SetFilePointerEx.argtypes = [C.c_void_p, C.c_int64, C.POINTER(C.c_int64), U32]
        k.SetFilePointerEx.restype = C.c_int
        k.FlushFileBuffers.argtypes = [C.c_void_p]
        k.FlushFileBuffers.restype = C.c_int
        k.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, U32, U32]
        k.VirtualAlloc.restype = C.c_void_p
        k.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, U32]
        k.VirtualFree.restype = C.c_int
        self.invalid_handle = C.c_void_p(-1).value

    @staticmethod
    def error(operation: str) -> OSError:
        error = C.WinError(C.get_last_error())
        return DeviceError(operation, error.winerror, error.strerror)

    def open(self, path: str, write: bool = False, unbuffered: bool = False):
        access = 0x80000000 | (0x40000000 if write else 0)
        flags = 0x20000000 | 0x80000000 if unbuffered else 0
        handle = self.kernel.CreateFileW(path, access, 3, None, 3, flags, None)
        if handle in (None, self.invalid_handle):
            raise self.error("Apertura del dispositivo")
        return handle

    def close(self, handle):
        if handle not in (None, self.invalid_handle):
            self.kernel.CloseHandle(handle)

    def ioctl(self, handle, code: int, data: bytes = b"", out_size: int = 0) -> bytes:
        source = C.create_string_buffer(data, len(data)) if data else None
        output = C.create_string_buffer(out_size) if out_size else None
        returned = U32()
        if not self.kernel.DeviceIoControl(handle, code, source, len(data),
                                           output, out_size, C.byref(returned), None):
            raise self.error(f"Controllo dispositivo 0x{code:08X}")
        return output.raw[:returned.value] if output else b""

    def allocate(self, length: int):
        pointer = self.kernel.VirtualAlloc(None, length, 0x1000 | 0x2000, 0x04)
        if not pointer:
            raise self.error("Allocazione del buffer allineato")
        return pointer

    def free(self, pointer):
        if pointer:
            self.kernel.VirtualFree(pointer, 0, 0x8000)

    def identify_ata(self, handle) -> bytes:
        header = AtaPassThrough()
        header.Length = C.sizeof(header)
        header.AtaFlags = 0x01 | 0x02  # DRDY_REQUIRED | DATA_IN
        header.DataTransferLength = 512
        header.TimeOutValue = 5
        header.DataBufferOffset = C.sizeof(header)
        header.CurrentTaskFile[1] = 1
        header.CurrentTaskFile[5] = 0xA0
        header.CurrentTaskFile[6] = 0xEC  # IDENTIFY DEVICE, read-only
        request = bytes(header)
        output = self.ioctl(handle, IOCTL_ATA_PASS_THROUGH, request, len(request) + 512)
        if len(output) < len(request) + 512:
            raise ValueError("ATA IDENTIFY senza dati completi.")
        returned = AtaPassThrough.from_buffer_copy(output[:C.sizeof(header)])
        if returned.CurrentTaskFile[6] & 0x21 or returned.DataTransferLength != 512:
            raise ValueError("ATA IDENTIFY ha restituito un errore.")
        return output[C.sizeof(header):C.sizeof(header) + 512]

    def identify_sat(self, handle, cdb_length: int = 16) -> bytes:
        if cdb_length not in (12, 16):
            raise ValueError("Variante SAT non supportata.")
        pointer = self.allocate(512)
        try:
            header = ScsiPassThroughDirect()
            header.Length = C.sizeof(header)
            header.CdbLength = cdb_length
            header.SenseInfoLength = 32
            header.DataIn = 1
            header.DataTransferLength = 512
            header.TimeOutValue = 5
            header.DataBuffer = pointer
            header.SenseInfoOffset = C.sizeof(header)
            # Both SAT variants issue the same read-only IDENTIFY command.
            header.Cdb[0] = 0x85 if cdb_length == 16 else 0xA1
            header.Cdb[1] = 4 << 1
            header.Cdb[2] = 0x0E
            header.Cdb[6 if cdb_length == 16 else 4] = 1
            header.Cdb[13 if cdb_length == 16 else 8] = 0xA0
            header.Cdb[14 if cdb_length == 16 else 9] = 0xEC
            request = bytes(header) + bytes(32)
            output = self.ioctl(handle, IOCTL_SCSI_PASS_THROUGH_DIRECT, request, len(request))
            if len(output) < C.sizeof(header):
                raise ValueError("Risposta SAT incompleta.")
            returned = ScsiPassThroughDirect.from_buffer_copy(output[:C.sizeof(header)])
            offset = returned.SenseInfoOffset
            length = returned.SenseInfoLength
            sense = output[offset:offset + length] if (offset >= C.sizeof(header)
                    and offset + length <= len(output)) else b""
            if not sat_identify_ok(returned.ScsiStatus, sense) or returned.DataTransferLength != 512:
                raise ValueError(f"SAT-{cdb_length} IDENTIFY non riuscito "
                                 f"(stato SCSI 0x{returned.ScsiStatus:02X}, dati {returned.DataTransferLength} byte).")
            return C.string_at(pointer, 512)
        finally:
            self.free(pointer)

    def disk_info(self, handle) -> dict:
        number_data = self.ioctl(handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, out_size=12)
        if len(number_data) != 12:
            raise ValueError("Numero del dispositivo non verificato.")
        device_type, number, _ = struct.unpack("<III", number_data)
        if device_type != 7:
            raise ValueError("Il dispositivo non è un disco.")
        length_data = self.ioctl(handle, IOCTL_DISK_GET_LENGTH_INFO, out_size=8)
        if len(length_data) != 8:
            raise ValueError("Capacità del dispositivo non verificata.")
        size = struct.unpack("<q", length_data)[0]
        geometry = self.ioctl(handle, IOCTL_DISK_GET_DRIVE_GEOMETRY, out_size=24)
        if len(geometry) < 24:
            raise ValueError("Dimensione del settore non verificata.")
        sector = struct.unpack_from("<I", geometry, 20)[0]
        serial, kind, evidence = "", "UNKNOWN", ""
        firmware_model, serial_source, bus_type = "", "DESCRIPTOR", None
        notes = []
        native = {"firmware_revision": "", "native_methods": (), "security_state": (),
                  "enhanced_erase_minutes": 0, "identify_transport": ""}
        try:
            descriptor = self.ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY,
                                    struct.pack("<III", 0, 0, 0), 8192)
            if len(descriptor) >= 28:
                offset = struct.unpack_from("<I", descriptor, 24)[0]
                if 0 < offset < len(descriptor):
                    serial = descriptor[offset:].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
                if len(descriptor) >= 32:
                    bus_type = struct.unpack_from("<I", descriptor, 28)[0]
        except OSError as error:
            notes.append("Descrittore Windows: " + str(error))
        transport_serial = serial
        probes = (("ATA", self.identify_ata),
                  ("SAT-16", lambda h: self.identify_sat(h, 16)),
                  ("SAT-12", lambda h: self.identify_sat(h, 12)))
        for name, identify in probes:
            try:
                identity = ata_identity(identify(handle))
                if not identity["serial"] or not identity["model"] or any(
                        not 32 <= ord(char) <= 126 for char in identity["serial"] + identity["model"]):
                    raise ValueError("IDENTIFY senza modello e seriale validi.")
                # A USB descriptor may identify the enclosure, while IDENTIFY
                # identifies the SATA drive. Keep both; never confuse them.
                if serial and norm(serial) != norm(identity["serial"]) and bus_type != 7:
                    raise ValueError("Seriali del dispositivo in conflitto fuori da USB.")
                serial, serial_source = identity["serial"], "ATA"
                firmware_model = identity["model"]
                native.update({key: identity[key] for key in ("firmware_revision", "native_methods", "security_state", "enhanced_erase_minutes")})
                native["identify_transport"] = name
                if identity["kind"] != "UNKNOWN":
                    kind, evidence = identity["kind"], name + " IDENTIFY, rotation rate"
                notes.append(name + " IDENTIFY disponibile.")
                break
            except OSError as error:
                notes.append(name + ": " + str(error))
            except ValueError as error:
                if "conflitto" in str(error):
                    raise
                notes.append(name + ": " + str(error))
        if kind == "UNKNOWN":
            try:
                seek = self.ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY,
                                  struct.pack("<III", 7, 0, 0), 12)
                if len(seek) >= 9 and seek[8] == 1:
                    kind, evidence = "HDD", "Windows: dispositivo con seek penalty"
            except OSError as error:
                notes.append("Seek penalty: " + str(error))
        return {"number": number, "size": size, "sector_size": sector,
                "serial": serial, "kind": kind, "evidence": evidence,
                "transport_serial": transport_serial, "serial_source": serial_source,
                "firmware_model": firmware_model, "bus_type": bus_type,
                "probe_notes": tuple(notes), **native}


def inspect_disk(number: int) -> dict:
    if not isinstance(number, int) or number < 0:
        raise ValueError("Numero di disco non valido.")
    api = NativeApi()
    # ATA/SCSI pass-through IOCTLs require read AND write handle access.
    # This probe issues metadata queries / IDENTIFY only; it never calls WriteFile.
    handle = api.open(r"\\.\PhysicalDrive" + str(number), write=True)
    try:
        return api.disk_info(handle)
    finally:
        api.close(handle)


class RawSession:
    allowed_kind, use_buffer = "HDD", True
    def __init__(self, disk: Disk):
        self.disk = disk
        self.api = NativeApi()
        self.handle = None
        self.volume_handles = []
        self.buffer = None
        self.buffer_size = 8 * 1024 * 1024
        self.size = disk.size
        self.warnings = []
        self.changed_offline = False
        self.finished = False
        self.wrote = False

    def _lock_volume(self, handle, path: str):
        for attempt in range(LOCK_ATTEMPTS):
            try:
                self.api.ioctl(handle, FSCTL_LOCK_VOLUME)
                return
            except OSError as error:
                if (getattr(error, "winerror", None) in (5, 32, 33)
                        and attempt + 1 < LOCK_ATTEMPTS):
                    time.sleep(LOCK_RETRY_DELAY)
                    continue
                raise Blocked(
                    f"Windows non consente l'accesso esclusivo al disco {self.disk.number}. "
                    "Chiudi le finestre di Esplora file e i programmi che usano questo disco, "
                    "poi riprova. Nessuna scrittura eseguita. "
                    f"Dettaglio: volume {path}; {error}"
                ) from error

    def _assert_identity(self):
        info = self.api.disk_info(self.handle)
        if info["number"] != self.disk.number or info["size"] != self.disk.size:
            raise Blocked("Il dispositivo aperto non corrisponde al disco selezionato.")
        if info["sector_size"] != self.disk.sector_size:
            raise Blocked("La dimensione dei settori è cambiata.")
        if not info["serial"] or norm(info["serial"]) != norm(self.disk.serial):
            raise Blocked("Il numero di serie del dispositivo aperto non corrisponde.")
        if self.allowed_kind == "HDD" and info["kind"] == "SSD":
            raise Blocked("Il dispositivo aperto è un SSD: nessuna sovrascrittura eseguita.")
        if self.disk.identity_source == "ATA":
            if (info.get("serial_source") != "ATA" or info["kind"] != self.allowed_kind
                    or not self.disk.firmware_model
                    or norm(info.get("firmware_model", "")) != norm(self.disk.firmware_model)):
                raise Blocked("L'identità ATA del dispositivo aperto non è più confermata.")
        if self.disk.firmware_revision and info.get("firmware_revision") != self.disk.firmware_revision:
            raise Blocked("Il firmware del disco è cambiato.")
        return info

    def _preflight(self):
        pass

    def __enter__(self):
        if self.disk.protected or self.disk.kind != self.allowed_kind or self.disk.simulated:
            raise Blocked("La sessione reale non accetta questo disco.")
        try:
            self.handle = self.api.open(r"\\.\PhysicalDrive" + str(self.disk.number),
                                        write=True, unbuffered=self.use_buffer)
            self._assert_identity()
            self._preflight()
            if not self.disk.offline:
                for path in self.disk.volume_paths:
                    handle = self.api.open(path.rstrip("\\"), write=True)
                    self.volume_handles.append(handle)
                    extents = self.api.ioctl(handle, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS,
                                            out_size=8 + 128 * 24)
                    if volume_disk_numbers(extents) != {self.disk.number}:
                        raise Blocked("Volume distribuito su più dischi: operazione bloccata.")
                    self._lock_volume(handle, path)
                    try:
                        self.api.ioctl(handle, FSCTL_DISMOUNT_VOLUME)
                    except OSError as error:
                        raise Blocked(
                            f"Windows non riesce a smontare un volume del disco {self.disk.number}. "
                            "Nessuna scrittura eseguita. "
                            f"Dettaglio: volume {path}; {error}"
                        ) from error
                # No override for volumes in use: a failed lock aborts before writing.
                from .inventory import powershell
                self.changed_offline = True
                powershell(f"$ErrorActionPreference='Stop'; Set-Disk -Number {self.disk.number} -IsOffline $true")
            self._assert_identity()
            if self.use_buffer:
                self.buffer = self.api.allocate(self.buffer_size)
            return self
        except BaseException:
            self.__exit__(*__import__("sys").exc_info())
            raise

    def write(self, data: bytes) -> int:
        length = len(data)
        if length > self.buffer_size or length % self.disk.sector_size:
            raise ValueError("Scrittura non allineata.")
        C.memmove(self.buffer, data, length)
        count = U32()
        # A failed call may already have modified part of the device.
        self.wrote = True
        if not self.api.kernel.WriteFile(self.handle, self.buffer, length, C.byref(count), None):
            raise self.api.error("Scrittura del disco")
        return count.value

    def read(self, length: int) -> bytes:
        if length > self.buffer_size or length % self.disk.sector_size:
            raise ValueError("Lettura non allineata.")
        count = U32()
        if not self.api.kernel.ReadFile(self.handle, self.buffer, length, C.byref(count), None):
            raise self.api.error("Lettura del disco")
        return C.string_at(self.buffer, count.value)

    def flush(self):
        if not self.api.kernel.FlushFileBuffers(self.handle):
            raise self.api.error("Conferma della scrittura sul dispositivo")

    def rewind(self):
        if not self.api.kernel.SetFilePointerEx(self.handle, 0, None, 0):
            raise self.api.error("Ripartenza della lettura dal primo settore")

    def finish(self):
        self.finished = True

    def __exit__(self, exc_type, exc_value, traceback):
        for handle in reversed(self.volume_handles):
            try:
                self.api.ioctl(handle, FSCTL_UNLOCK_VOLUME)
            except OSError:
                pass
            self.api.close(handle)
        self.volume_handles.clear()
        if self.handle is not None:
            if self.wrote:
                try:
                    self.api.ioctl(self.handle, IOCTL_DISK_UPDATE_PROPERTIES)
                except OSError as error:
                    self.warnings.append("Aggiornamento dell'elenco partizioni non riuscito: " + str(error))
            if self.changed_offline and (self.finished or not self.wrote):
                try:
                    self._assert_identity()
                    from .inventory import powershell
                    powershell(f"$ErrorActionPreference='Stop'; Set-Disk -Number {self.disk.number} -IsOffline $false")
                except Exception as error:
                    self.warnings.append("Disco lasciato offline: " + str(error))
            elif self.changed_offline:
                self.warnings.append("Disco lasciato offline dopo l'operazione incompleta.")
            self.api.close(self.handle)
            self.handle = None
        self.api.free(self.buffer)
        self.buffer = None
        return False
