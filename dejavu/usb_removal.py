"""Best-effort, non-forced safe removal of completed USB storage devices.

The native operation runs in a bounded child process, after erasure handles
have closed and the erasure report has been saved. No hub, host controller,
internal SATA device, unselected disk or unsuccessful job may be removed.
"""
from __future__ import annotations

from dataclasses import asdict
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from .core import Disk, JobResult, norm, stamp, usable_serial
from .inventory import WindowsInventory, powershell
from .reports import atomic_text


HELPER_TIMEOUT = 90
DISK_CLASS = "{4D36E967-E325-11CE-BFC1-08002BE10318}"
VOLUME_CLASS = "{71A27CDD-812A-11D0-BEC7-08002BE2092F}"
STORAGE_SERVICES = {"USBSTOR", "UASPSTOR"}
USB_DEVICE = re.compile(r"USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}(?:&[^\\]+)?\\[^\\]+$", re.I)
PNP_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$rows = @(Get-CimInstance Win32_DiskDrive -ErrorAction Stop | ForEach-Object {
    [pscustomobject]@{Number=[int]$_.Index; InstanceId=[string]$_.PNPDeviceID}
})
[pscustomobject]@{Disks=$rows} | ConvertTo-Json -Depth 4 -Compress
'''


def outcome(numbers, status, message, device_id="", **details):
    return {"disk_numbers": sorted(numbers), "status": status, "message": message,
            "device_id": device_id, "finished_at": stamp(), **details}


def disk_identity(disk):
    # Volumes/offline/security state can legitimately change during erasure.
    # A disk number or the shared bridge serial is never sufficient identity.
    return (disk.number, norm(disk.serial), norm(disk.model), disk.size,
            disk.sector_size, disk.bus, disk.kind, disk.identity_source,
            norm(disk.firmware_model), disk.firmware_revision)


def pnp_disks():
    rows = json.loads(powershell(PNP_SCRIPT, timeout=20)).get("Disks")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Elenco dei dispositivi Windows incompleto.")
    mapping = {}
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("Number")) is not int
                or row["Number"] < 0 or not isinstance(row.get("InstanceId"), str)
                or not row["InstanceId"].strip() or row["Number"] in mapping):
            raise ValueError("Associazione fra dischi e dispositivi Windows ambigua.")
        mapping[row["Number"]] = row["InstanceId"].upper()
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Identificativi dei dispositivi Windows duplicati.")
    return mapping


class ConfigManager:
    """Small typed CfgMgr32 binding; only request-eject can change device state."""
    def __init__(self):
        if os.name != "nt":
            raise OSError("La rimozione USB reale richiede Windows.")
        library = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cfgmgr32.dll"
        self.api = ctypes.WinDLL(str(library), use_last_error=True)
        u32, pu32 = ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
        signatures = {
            "CM_Locate_DevNodeW": [pu32, ctypes.c_wchar_p, u32],
            "CM_Get_Parent": [pu32, u32, u32],
            "CM_Get_Child": [pu32, u32, u32],
            "CM_Get_Sibling": [pu32, u32, u32],
            "CM_Get_Device_ID_Size": [pu32, u32, u32],
            "CM_Get_Device_IDW": [u32, ctypes.c_wchar_p, u32, u32],
            "CM_Get_DevNode_Registry_PropertyW": [u32, u32, pu32, ctypes.c_void_p, pu32, u32],
            "CM_Request_Device_EjectW": [u32, pu32, ctypes.c_wchar_p, u32, u32],
        }
        for name, arguments in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, u32

    @staticmethod
    def check(code):
        if code:
            raise OSError(f"Interrogazione PnP non confermata (codice 0x{code:08X}).")

    def locate(self, instance_id):
        node = ctypes.c_uint32()
        self.check(self.api.CM_Locate_DevNodeW(ctypes.byref(node), instance_id, 0))
        return node.value

    def identifier(self, node):
        size = ctypes.c_uint32()
        self.check(self.api.CM_Get_Device_ID_Size(ctypes.byref(size), node, 0))
        if not 0 < size.value < 4096:
            raise ValueError("Identificativo PnP non valido.")
        buffer = ctypes.create_unicode_buffer(size.value + 1)
        self.check(self.api.CM_Get_Device_IDW(node, buffer, len(buffer), 0))
        return buffer.value.upper()

    def related(self, function, node):
        other = ctypes.c_uint32()
        code = getattr(self.api, function)(ctypes.byref(other), node, 0)
        if code == 0x0D:  # CR_NO_SUCH_DEVNODE: no child/sibling/parent.
            return None
        self.check(code)
        return other.value

    def property(self, node, key):
        kind, size = ctypes.c_uint32(), ctypes.c_uint32()
        function = self.api.CM_Get_DevNode_Registry_PropertyW
        code = function(node, key, ctypes.byref(kind), None, ctypes.byref(size), 0)
        if code not in (0, 0x1A) or not 0 < size.value <= 65536:
            self.check(code or 1)
        buffer = ctypes.create_string_buffer(size.value)
        self.check(function(node, key, ctypes.byref(kind), buffer, ctypes.byref(size), 0))
        if kind.value == 4 and size.value == 4:  # REG_DWORD
            return int.from_bytes(buffer.raw[:4], "little")
        if kind.value == 1 and size.value % 2 == 0:  # REG_SZ, Windows UTF-16LE.
            return buffer.raw[:size.value].decode("utf-16-le").rstrip("\0").upper()
        raise ValueError("Proprietà PnP di tipo inatteso.")

    def storage_root(self, disk_id):
        node, seen = self.locate(disk_id), set()
        for _ in range(16):
            identifier = self.identifier(node)
            if identifier in seen:
                raise ValueError("Percorso PnP circolare.")
            seen.add(identifier)
            if identifier.startswith("USB\\"):
                # Stop at the first USB node. Never climb to a USB hub or a
                # composite parent to force an unsupported storage removal.
                if (USB_DEVICE.fullmatch(identifier)
                        and self.property(node, 5) in STORAGE_SERVICES
                        and self.property(node, 16) & 4):  # CM_DEVCAP_REMOVABLE
                    return identifier
                return None
            if identifier.startswith(("PCI\\", "ROOT\\", "ACPI\\")):
                return None
            node = self.related("CM_Get_Parent", node)
            if node is None:
                return None
        raise ValueError("Percorso PnP troppo lungo.")

    def branch(self, root_id):
        root = self.locate(root_id)
        if (not USB_DEVICE.fullmatch(self.identifier(root))
                or self.property(root, 5) not in STORAGE_SERVICES
                or not self.property(root, 16) & 4):
            raise ValueError("Il dispositivo non è una unità USB di archiviazione rimovibile.")
        pending, entries, seen = [root], [], set()
        while pending:
            node = pending.pop()
            identifier = self.identifier(node)
            if identifier in seen or len(seen) >= 256:
                raise ValueError("Struttura dei dispositivi USB ambigua.")
            seen.add(identifier)
            class_id = self.property(node, 9)
            if node != root and class_id not in (DISK_CLASS, VOLUME_CLASS):
                raise ValueError("La docking contiene funzioni non riconosciute: rimozione automatica esclusa.")
            entries.append((identifier, class_id))
            child = self.related("CM_Get_Child", node)
            siblings = set()
            while child is not None:
                if child in siblings:
                    raise ValueError("Struttura dei dispositivi USB circolare.")
                siblings.add(child)
                pending.append(child)
                child = self.related("CM_Get_Sibling", child)
        return tuple(sorted(entries))

    def eject(self, root_id, expected_branch):
        # Recheck the complete branch immediately before the single request.
        if self.branch(root_id) != expected_branch:
            raise ValueError("I dispositivi della docking sono cambiati: rimozione annullata.")
        node = self.locate(root_id)
        veto = ctypes.c_uint32()
        name = ctypes.create_unicode_buffer(260)
        code = self.api.CM_Request_Device_EjectW(node, ctypes.byref(veto), name, len(name), 0)
        return int(code), veto.value, name.value


def plan_docks(results, inventory, mapping, manager):
    """Build plans from a fresh protected inventory and ALL native disk children."""
    if not inventory.protection_ok or inventory.error or not any(d.protected for d in inventory.disks):
        raise ValueError("Protezione delle unità in uso non confermata.")
    fresh = {disk.number: disk for disk in inventory.disks}
    if len(fresh) != len(inventory.disks) or set(fresh) != set(mapping):
        raise ValueError("Gli elenchi Windows dei dischi non concordano: nessuna rimozione automatica.")
    selected = {result.disk.number: result for result in results}
    if len(selected) != len(results):
        raise ValueError("Numeri di disco duplicati nel lotto.")
    groups, skipped = {}, []
    for result in results:
        disk = result.disk
        if disk.bus != "USB":
            continue
        current = fresh.get(disk.number)
        if current is None or disk_identity(current) != disk_identity(disk):
            raise ValueError("Un disco USB del lotto è assente o ha cambiato identità: rimozione automatica esclusa.")
        root = manager.storage_root(mapping[disk.number])
        if root is None:
            skipped.append(outcome([disk.number], "SKIPPED", "Il collegamento non espone una docking USB rimovibile supportata."))
            continue
        groups.setdefault(root, []).append(disk.number)
    plans = []
    for root, numbers in groups.items():
        try:
            branch = manager.branch(root)
            disk_ids = {identifier for identifier, class_id in branch if class_id == DISK_CLASS}
            members = {number for number, identifier in mapping.items() if identifier in disk_ids}
            if not disk_ids or disk_ids != {mapping[n] for n in members} or members != set(numbers):
                raise ValueError("La docking contiene anche dischi non selezionati o non identificati nel lotto.")
            for number in members:
                disk, result = fresh[number], selected[number]
                if (disk.bus != "USB" or disk.protected or disk.read_only
                        or not usable_serial(disk.serial)
                        or sum(norm(other.serial) == norm(disk.serial) for other in fresh.values()) != 1
                        or disk_identity(disk) != disk_identity(result.disk)
                        or result.status != "SUCCESS" or result.warnings):
                    raise ValueError("Almeno un disco è protetto, cambiato o senza un esito completo privo di avvisi.")
            plans.append((root, tuple(sorted(members)), branch))
        except Exception as error:
            skipped.append(outcome(numbers, "SKIPPED", str(error), root))
    return plans, skipped


def perform_removal(results, inventory, mapping, manager):
    plans, skipped = plan_docks(results, inventory, mapping, manager)
    yield from skipped
    for root, numbers, branch in plans:
        try:
            code, veto, name = manager.eject(root, branch)
            if code == 0:
                yield outcome(numbers, "EJECTED", "Docking espulsa da Windows. Puoi spegnerla e sostituire i dischi.", root,
                              configret=code, veto_type=veto, veto_name=name)
            else:
                message = "Windows non ha autorizzato la rimozione sicura"
                if veto in (2, 3, 4, 5):
                    message += ": dispositivo ancora in uso"
                message += f" (codice 0x{code:08X}, motivo {veto}). Nessuna espulsione forzata."
                yield outcome(numbers, "NOT_CONFIRMED", message, root,
                              configret=code, veto_type=veto, veto_name=name)
        except Exception as error:
            yield outcome(numbers, "NOT_CONFIRMED", "Rimozione non confermata: " + str(error), root)


def _decode_results(raw):
    results = []
    for record in raw:
        disk_data = dict(record["disk"])
        for field in ("protected_reasons", "volume_paths", "probe_notes", "native_methods", "security_state"):
            if field in disk_data:
                disk_data[field] = tuple(disk_data[field])
        results.append(JobResult(Disk(**disk_data), record["status"], "", warnings=list(record["warnings"])))
    if not results or any(result.disk.bus != "USB" or result.disk.simulated for result in results):
        raise ValueError("Richiesta di rimozione non valida.")
    return results


def helper_main(request_path):
    """Internal child entry, intentionally outside the main application's mutex."""
    path = Path(request_path)
    response = path.with_name("risposta.json")
    records = []
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
        if os.name != "nt" or request.get("format") != 1:
            raise ValueError("Richiesta Windows non valida.")
        results = _decode_results(request["results"])
        atomic_text(response, json.dumps({"complete": False, "records": records}, ensure_ascii=False))
        inventory = WindowsInventory(Path(request["app_path"]), Path(request["report_path"])).scan()
        mapping, manager = pnp_disks(), ConfigManager()
        for record in perform_removal(results, inventory, mapping, manager):
            records.append(record)
            # A later driver stall must not lose already confirmed removals.
            atomic_text(response, json.dumps({"complete": False, "records": records}, ensure_ascii=False))
        atomic_text(response, json.dumps({"complete": True, "records": records}, ensure_ascii=False))
        return 0
    except Exception as error:
        atomic_text(response, json.dumps({"complete": False, "records": records, "error": str(error)}, ensure_ascii=False))
        return 1


def remove_completed(results, app_path, report_path, cancel):
    usb = [result for result in results if result.disk.bus == "USB"]
    if not usb:
        return []
    numbers = {result.disk.number for result in usb}
    if cancel.is_set():
        return [outcome(numbers, "SKIPPED", "Lotto interrotto: rimozione automatica esclusa.")]
    if any(result.disk.simulated for result in results):
        return [outcome(numbers, "SIMULATED", "Simulazione: nessuna docking fisica è stata espulsa.")]
    if not any(result.status == "SUCCESS" and not result.warnings for result in usb):
        return [outcome(numbers, "SKIPPED", "Nessun disco USB con esito completo privo di avvisi: rimozione automatica esclusa.")]
    with tempfile.TemporaryDirectory(prefix="dejavu-espulsione-") as directory:
        request = Path(directory) / "richiesta.json"
        response = request.with_name("risposta.json")
        atomic_text(request, json.dumps({"format": 1, "app_path": str(app_path), "report_path": str(report_path),
            "results": [{"disk": asdict(result.disk), "status": result.status, "warnings": result.warnings} for result in usb]}, ensure_ascii=False))
        entry = [] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve().parents[1] / "main.py")]
        command = [sys.executable, *entry, "--rimozione-usb-interna", str(request)]
        error = ""
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=HELPER_TIMEOUT, creationflags=0x08000000, check=True)
        except subprocess.TimeoutExpired:
            error = f"Windows non ha concluso la rimozione entro {HELPER_TIMEOUT} secondi. Verifica manualmente la docking."
        except Exception as exception:
            error = "Rimozione automatica non confermata: " + str(exception)
        records = []
        if response.exists():
            payload = json.loads(response.read_text(encoding="utf-8"))
            for record in payload.get("records", []):
                members = record.get("disk_numbers", [])
                if (not members or not set(members) <= numbers
                        or record.get("status") not in ("EJECTED", "SKIPPED", "NOT_CONFIRMED")):
                    raise ValueError("Risposta di rimozione non valida.")
                records.append(record)
                numbers.difference_update(members)
            error = error or payload.get("error", "")
        if numbers:
            records.append(outcome(numbers, "NOT_CONFIRMED", error or "Windows non ha confermato la rimozione. Verifica manualmente la docking."))
        return records
