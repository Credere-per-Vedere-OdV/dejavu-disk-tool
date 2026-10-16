"""Native SATA SSD operations on a held and identity-checked device handle.

Block Erase is preferred. Enhanced Security Erase uses a DPAPI-protected
temporary password. Native completion is not a Purge certification.
"""
from __future__ import annotations

import base64
import ctypes as C
import json
import os
from pathlib import Path
import secrets
from threading import Event, Thread
import time
import uuid

from .core import Blocked, Cancelled, norm, stamp
from .reports import atomic_text
from .windows_io import (RawSession, AtaPassThrough, ScsiPassThroughDirect, U32,
                         IOCTL_ATA_PASS_THROUGH, IOCTL_SCSI_PASS_THROUGH_DIRECT)


class DataBlob(C.Structure):
    _fields_ = [("size", U32), ("data", C.c_void_p)]


def protect_password(value: bytes, decrypt=False) -> bytes:
    crypt = C.WinDLL("crypt32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    function = getattr(crypt, "CryptUnprotectData" if decrypt else "CryptProtectData")
    function.argtypes = [C.POINTER(DataBlob), C.c_void_p, C.c_void_p, C.c_void_p,
                         C.c_void_p, U32, C.POINTER(DataBlob)]
    function.restype = C.c_int
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [C.c_void_p], C.c_void_p
    buffer = C.create_string_buffer(value)
    source, output = DataBlob(len(value), C.cast(buffer, C.c_void_p)), DataBlob()
    if not function(C.byref(source), None, None, None, None, 1, C.byref(output)):
        raise OSError("Protezione della chiave di recupero SSD non riuscita.")
    try:
        return C.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def sat_registers(status: int, sense: bytes) -> tuple:
    if status not in (0, 2) or len(sense) < 8 or sense[0] & 0x7F not in (0x72, 0x73):
        raise OSError("Il collegamento non restituisce i registri ATA del comando SSD.")
    if sense[1] & 0x0F not in (0, 1) or sense[2:4] != b"\x00\x1D":
        raise OSError("Errore SCSI durante il comando SSD.")
    end, position = 8 + sense[7], 8
    if end > len(sense):
        raise OSError("Risposta ATA SSD incompleta.")
    while position + 2 <= end:
        length = sense[position + 1] + 2
        if position + length > end:
            break
        d = sense[position:position + length]
        if d[0] == 9 and len(d) >= 14:
            return (d[3], d[5], d[7], d[9], d[11], d[12], d[13], d[4], bool(d[2] & 1))
        position += length
    raise OSError("Registri ATA assenti: comando SSD non confermato.")


def taskfile(api, handle, transport, command, feature=0, lba=0,
             extended=False, data=b"", timeout=10) -> tuple:
    if (command, feature) not in ((0xB4, 0), (0xB4, 0x12), (0xF1, 0),
                                 (0xF2, 0), (0xF3, 0), (0xF4, 0), (0xF6, 0)):
        raise ValueError("Comando SSD non consentito.")
    if len(data) not in (0, 512) or extended != (command == 0xB4):
        raise ValueError("Parametri ATA SSD non validi.")
    if bool(data) != (command in (0xF1, 0xF2, 0xF4, 0xF6)):
        raise ValueError("Trasferimento dati non valido per il comando SSD.")
    if command == 0xB4 and lba != (0x426B4572 if feature == 0x12 else 0):
        raise ValueError("Firma del comando Sanitize non valida.")
    if command == 0xF4 and data[:2] != b"\x02\x00":
        raise ValueError("Solo Enhanced Security Erase è consentito.")
    low = (feature, int(bool(data)), lba & 255, lba >> 8 & 255, lba >> 16 & 255, 0x40, command, 0)
    high = (feature >> 8, 0, lba >> 24 & 255, lba >> 32 & 255, lba >> 40 & 255, 0, 0, 0)
    if transport == "ATA":
        header = AtaPassThrough()
        header.Length = C.sizeof(header)
        header.AtaFlags = 0x01 | (0x10 if extended else 0) | (0x04 if data else 0)
        header.DataTransferLength, header.TimeOutValue = len(data), timeout
        header.DataBufferOffset = C.sizeof(header) if data else 0
        header.CurrentTaskFile[:], header.PreviousTaskFile[:] = low, high
        request = bytes(header) + data
        response = api.ioctl(handle, IOCTL_ATA_PASS_THROUGH, request, len(request))
        if len(response) < C.sizeof(header):
            raise OSError("Risposta ATA SSD incompleta.")
        returned = AtaPassThrough.from_buffer_copy(response[:C.sizeof(header)])
        r = returned.CurrentTaskFile
        registers = (r[0], r[1], r[2], r[3], r[4], r[5], r[6], returned.PreviousTaskFile[1], extended)
    elif transport == "SAT-16":
        pointer = api.allocate(len(data)) if data else None
        try:
            if data:
                C.memmove(pointer, data, len(data))
            header = ScsiPassThroughDirect()
            header.Length, header.CdbLength, header.SenseInfoLength = C.sizeof(header), 16, 32
            header.DataIn = 0 if data else 2
            header.DataTransferLength, header.TimeOutValue = len(data), timeout
            header.DataBuffer, header.SenseInfoOffset = pointer, C.sizeof(header)
            header.Cdb[:] = (0x85, ((5 if data else 3) << 1) | int(extended),
                            0x26 if data else 0x20, high[0], low[0], high[1], low[1],
                            high[2], low[2], high[3], low[3], high[4], low[4], low[5], command, 0)
            request = bytes(header) + bytes(32)
            response = api.ioctl(handle, IOCTL_SCSI_PASS_THROUGH_DIRECT, request, len(request))
            if len(response) < C.sizeof(header):
                raise OSError("Risposta SAT SSD incompleta.")
            returned = ScsiPassThroughDirect.from_buffer_copy(response[:C.sizeof(header)])
            offset, length = returned.SenseInfoOffset, returned.SenseInfoLength
            if offset < C.sizeof(header) or offset + length > len(response):
                raise OSError("Diagnostica SAT SSD incompleta.")
            registers = sat_registers(returned.ScsiStatus, response[offset:offset + length])
        finally:
            api.free(pointer)
    else:
        raise ValueError("Trasporto ATA non consentito.")
    if registers[0] or registers[6] & 0xA9 or not registers[6] & 0x40:
        raise OSError(f"Il dispositivo ha rifiutato il comando SSD 0x{command:02X}/0x{feature:02X} "
                      f"(errore 0x{registers[0]:02X}, stato 0x{registers[6]:02X}).")
    if extended and not registers[8]:
        raise OSError("Il collegamento non conferma i registri ATA a 48 bit.")
    return registers


def sanitize_state(registers):
    flags = registers[7]
    if flags & 0x1F or flags & 0xC0 == 0xC0:
        raise OSError("Stato Sanitize ATA sconosciuto, contraddittorio o di errore.")
    if flags & 0x20:
        raise Blocked("Sanitizzazione SSD congelata dal dispositivo. Affidarlo al responsabile tecnico.")
    if flags & 0x40:
        progress = 100 * (registers[2] | registers[3] << 8) / 65536
        return "RUNNING", min(99.9, progress)
    if flags & 0x80:
        return "SUCCESS", 100
    return "NEVER", 0


class SsdSession(RawSession):
    allowed_kind, use_buffer = "SSD", False

    def __init__(self, disk, recovery_folder: Path):
        super().__init__(disk)
        self.recovery_folder = recovery_folder
        self.transport, self.method = "", ""
        self.native_details = {"completion": "not_started", "firmware": disk.firmware_revision}
        self.journal, self.password = None, None

    def _preflight(self):
        info = self._assert_identity()
        methods = set(info.get("native_methods", ()))
        if self.disk.identity_source != "ATA" or info["kind"] != "SSD":
            raise Blocked("SSD SATA non identificato con certezza.")
        if norm(info.get("firmware_model", "")) == "RUGGEDSSD4":
            raise Blocked("Questo dispositivo ha limitazioni note di sanitizzazione.")
        if "ATA_SANITIZE_BLOCK" in methods and "ATA_SANITIZE_BLOCK" in self.disk.native_methods:
            errors = []
            for transport in (("SAT-16",) if self.disk.bus == "USB" else ("ATA", "SAT-16")):
                try:
                    state, _ = sanitize_state(taskfile(self.api, self.handle, transport, 0xB4, extended=True))
                    if state == "RUNNING":
                        raise Blocked("Una sanitizzazione SSD è già in corso. Attendere e affidarlo al responsabile tecnico.")
                    self.transport, self.method = transport, "SSD SATA: ATA Sanitize Block Erase"
                    break
                except Blocked:
                    raise
                except OSError as error:
                    errors.append(str(error))
            if not self.transport:
                raise Blocked("Windows o il collegamento non consentono Sanitize sullo SSD. "
                              "Affidarlo al responsabile tecnico. " + " | ".join(errors))
        elif "ATA_SECURITY_ENHANCED" in methods and "ATA_SECURITY_ENHANCED" in self.disk.native_methods:
            if info.get("security_state"):
                raise Blocked("Sicurezza ATA dello SSD non disponibile: " + ", ".join(info["security_state"]))
            self.transport = "ATA" if info.get("identify_transport") == "ATA" else "SAT-16"
            if self.transport == "SAT-16":
                from .windows_io import ata_identity
                identity = ata_identity(self.api.identify_sat(self.handle, 16))
                if norm(identity["serial"]) != norm(self.disk.serial) or identity["kind"] != "SSD":
                    raise Blocked("SSD diverso durante il controllo del collegamento.")
            self.method = "SSD SATA: ATA Enhanced Security Erase"
        else:
            raise Blocked("SSD senza procedura nativa supportata da questa versione.")
        self.native_details.update(method=self.method, transport=self.transport)

    def _emit(self, emit, percent=None, message="Sanitizzazione interna al dispositivo"):
        emit({"phase": "Sanitizzazione SSD", "percent": percent, "native": True, "message": message})

    def sanitize(self, cancel: Event, emit):
        self._assert_identity()
        if cancel.is_set():
            raise Cancelled("Interrotto prima della sanitizzazione SSD.")
        if self.method.endswith("Block Erase"):
            self.wrote = True  # A failed submission may still have reached the device.
            self.native_details["completion"] = "unconfirmed"
            taskfile(self.api, self.handle, self.transport, 0xB4, feature=0x12,
                     lba=0x426B4572, extended=True)
            deadline, never_deadline = time.monotonic() + 86400, time.monotonic() + 30
            while True:
                state, percent = sanitize_state(taskfile(self.api, self.handle, self.transport, 0xB4, extended=True))
                self.native_details["device_state"] = state
                self._emit(emit, percent if state != "NEVER" else None)
                if state == "SUCCESS":
                    break
                if time.monotonic() > deadline or (state == "NEVER" and time.monotonic() > never_deadline):
                    raise OSError("Il dispositivo non ha confermato il completamento di Sanitize.")
                time.sleep(1)
        else:
            self.password = secrets.token_hex(16).encode("ascii")
            protected = protect_password(self.password)
            self.recovery_folder.mkdir(parents=True, exist_ok=True)
            self.journal = self.recovery_folder / ("SSD-" + uuid.uuid4().hex + ".json")
            payload = {"serial": self.disk.serial, "model": self.disk.firmware_model,
                       "firmware": self.disk.firmware_revision, "created_at": stamp(),
                       "owner_pid": os.getpid(), "method": self.method,
                       "password_dpapi": base64.b64encode(protected).decode("ascii")}
            atomic_text(self.journal, json.dumps(payload, ensure_ascii=False, indent=2))
            self.native_details["recovery_record"] = str(self.journal)
            data = bytearray(512)
            data[2:34] = self.password
            if cancel.is_set():
                self.journal.unlink()
                self.journal = None
                raise Cancelled("Interrotto prima della sanitizzazione SSD.")
            self.wrote = True
            self.native_details["completion"] = "unconfirmed"
            taskfile(self.api, self.handle, self.transport, 0xF1, data=bytes(data))
            taskfile(self.api, self.handle, self.transport, 0xF3)
            data[0] = 2  # Enhanced erase, user password.
            heartbeat_done = Event()
            def heartbeat():
                while not heartbeat_done.wait(1):
                    self._emit(emit, message="Enhanced Security Erase in corso; attendere la conferma del dispositivo.")
            thread = Thread(target=heartbeat, name="dejavu-ssd-status", daemon=True)
            self._emit(emit, message="Enhanced Security Erase: comando interno in corso.")
            thread.start()
            try:
                taskfile(self.api, self.handle, self.transport, 0xF4, data=bytes(data), timeout=86400)
            finally:
                heartbeat_done.set()
                thread.join(timeout=2)
            info = self._assert_identity()
            if info.get("security_state"):
                raise OSError("La sicurezza ATA non risulta rimossa dopo Enhanced Security Erase.")
            self.native_details["device_state"] = "SECURITY_DISABLED"
        self._assert_identity()
        self.native_details["completion"] = "device_confirmed"
        if cancel.is_set():
            self.warnings.append("Interruzione richiesta dopo l'avvio: la cancellazione nativa SSD è stata seguita fino al termine.")
        self._emit(emit, 100, "Esito della cancellazione nativa confermato dal dispositivo.")

    def finish(self):
        if self.native_details["completion"] != "device_confirmed":
            raise OSError("Sanitizzazione SSD non confermata.")
        super().finish()
        if self.journal is not None:
            try:
                self.journal.unlink()
                self.native_details["recovery_record_removed"] = True
            except OSError as error:
                self.warnings.append("Registro di recupero conservato: " + str(error))

    def __exit__(self, *args):
        if self.wrote and not self.finished:
            self.warnings.append("Operazione nativa SSD non confermata: affidare il disco al responsabile tecnico.")
            if self.journal is not None:
                self.warnings.append("Conservare il registro " + str(self.journal) +
                                     " e il profilo Windows usato: potrebbero servire per rimuovere la password temporanea.")
        self.password = None
        return super().__exit__(*args)


def recovery_owner_running(pid: int) -> bool:
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [U32, C.c_int, U32], C.c_void_p
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = [C.c_void_p, U32], U32
    kernel.CloseHandle.argtypes = [C.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        if C.get_last_error() == 87:
            return False
        raise Blocked("Impossibile verificare che la precedente operazione SSD sia terminata.")
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        if state not in (0, 258):
            raise Blocked("Stato del precedente processo SSD non verificato.")
        return state == 258
    finally:
        kernel.CloseHandle(handle)


def recover_security(disk, fresh, record: Path, confirmation: str):
    """Technician-only removal of this application's temporary password.

    This function never sends an erase command or attests data erasure.
    """
    payload = json.loads(record.read_text(encoding="utf-8"))
    if not fresh.protection_ok or fresh.error or disk.protected or disk.read_only or disk.simulated:
        raise Blocked("Recupero SSD bloccato dalle protezioni delle unità in uso.")
    current = [d for d in fresh.disks if d.number == disk.number]
    if len(current) != 1 or current[0].key != disk.key:
        raise Blocked("SSD cambiato o rilevamento ambiguo.")
    if (disk.kind != "SSD" or disk.identity_source != "ATA" or disk.bus not in ("SATA", "ATA", "USB")
            or norm(confirmation) != norm(disk.serial)
            or norm(payload.get("serial", "")) != norm(disk.serial)
            or norm(payload.get("model", "")) != norm(disk.firmware_model)
            or payload.get("firmware", "") != disk.firmware_revision
            or sum(norm(d.serial) == norm(disk.serial) for d in fresh.disks) != 1):
        raise Blocked("Registro, numero di serie e SSD non corrispondono con certezza.")
    pid = payload.get("owner_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or recovery_owner_running(pid):
        raise Blocked("La precedente operazione SSD potrebbe essere ancora attiva.")
    password = protect_password(base64.b64decode(payload["password_dpapi"], validate=True), decrypt=True)
    if len(password) != 32:
        raise Blocked("Chiave di recupero SSD non valida.")
    class RecoverySession(RawSession):
        allowed_kind, use_buffer = "SSD", False
    session = RecoverySession(disk)
    with session:
        info = session._assert_identity()
        state = info.get("security_state", ())
        if "congelata" in state or "tentativi esauriti" in state or "stato non valido" in state:
            raise Blocked("Sicurezza ATA non disponibile per il recupero.")
        data = bytearray(512)
        data[2:34] = password
        transport = "ATA" if info.get("identify_transport") == "ATA" else "SAT-16"
        if "bloccata" in state:
            session.wrote = True
            taskfile(session.api, session.handle, transport, 0xF2, data=bytes(data))
        if "abilitata" in state or "bloccata" in state:
            session.wrote = True
            taskfile(session.api, session.handle, transport, 0xF6, data=bytes(data))
        if session._assert_identity().get("security_state"):
            raise OSError("Rimozione della password SSD non confermata.")
        session.finish()
    record.unlink()
    return "Password temporanea rimossa. Questo recupero non attesta la cancellazione dei dati: ripetere la sanitizzazione."
