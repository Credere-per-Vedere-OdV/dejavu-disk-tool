"""Read-only inventory via the Windows Storage module, no WMIC dependency."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys

from .core import Disk, Inventory, norm, usable_serial


INVENTORY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$disks = @(Get-Disk -ErrorAction Stop)
$partitions = @(Get-Partition -ErrorAction Stop)
$osInfo = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
$systemLetter = $osInfo.SystemDrive.Substring(0,1)
$systemPartitions = @($partitions | Where-Object { $_.DriveLetter -eq $systemLetter })
if ($systemPartitions.Count -ne 1) { throw 'Partizione Windows non identificata in modo univoco.' }
$systemNumber = [int]$systemPartitions[0].DiskNumber
if (@($disks | Where-Object { $_.Number -eq $systemNumber }).Count -ne 1) {
    throw 'Disco Windows non presente nel rilevamento.'
}
if (@($disks | Where-Object { $_.IsSystem -or $_.IsBoot }).Count -eq 0) {
    throw 'Unità di avvio non identificate: protezione incompleta.'
}
$protected = @{}
function Protect-Disk([int]$number, [string]$reason) {
    if (-not $protected.ContainsKey($number)) { $protected[$number] = @() }
    $protected[$number] += $reason
}
Protect-Disk $systemNumber 'Windows in esecuzione'
foreach ($disk in $disks) {
    if ($disk.IsBoot) { Protect-Disk ([int]$disk.Number) 'Partizione Windows di avvio' }
    if ($disk.IsSystem) { Protect-Disk ([int]$disk.Number) 'Partizione di sistema / EFI in uso' }
}
$pagefiles = @(Get-CimInstance Win32_PageFileUsage -ErrorAction Stop)
foreach ($pf in $pagefiles) {
    if ($pf.Name -notmatch '^[A-Za-z]:') { throw 'File di paging non mappabile.' }
    $vs = @(Get-Volume -FilePath $pf.Name -ErrorAction Stop)
    if ($vs.Count -ne 1) { throw 'Volume del file di paging non identificato.' }
    $pps = @(Get-Partition -Volume $vs[0] -ErrorAction Stop)
    if ($pps.Count -ne 1) { throw 'Disco del file di paging non identificato.' }
    Protect-Disk ([int]$pps[0].DiskNumber) 'File di paging in uso'
}
foreach ($path in @($env:DEJAVU_APP_PATH, $env:DEJAVU_RUNTIME_PATH, $env:DEJAVU_REPORT_PATH)) {
    if ($path -notmatch '^[A-Za-z]:') { throw 'Programma e rapporti devono risiedere su una unità locale identificabile.' }
    # Resolve the actual volume, including a volume mounted inside a folder.
    $vs = @(Get-Volume -FilePath $path -ErrorAction Stop)
    if ($vs.Count -ne 1) { throw 'Volume del programma o dei rapporti non identificato.' }
    $pps = @(Get-Partition -Volume $vs[0] -ErrorAction Stop)
    if ($pps.Count -ne 1) { throw 'Disco del programma o dei rapporti non identificato.' }
    Protect-Disk ([int]$pps[0].DiskNumber) 'Programma o rapporti in uso'
}
$physical = @()
try { $physical = @(Get-PhysicalDisk -ErrorAction Stop) } catch { }
$rows = @()
foreach ($disk in $disks) {
    $serial = ([string]$disk.SerialNumber).Trim()
    $unique = ([string]$disk.UniqueId).Trim()
    $pd = @($physical | Where-Object {
        $_.Size -eq $disk.Size -and (
            ($unique -ne '' -and ([string]$_.UniqueId).Trim() -eq $unique) -or
            ($serial -ne '' -and ([string]$_.SerialNumber).Trim() -eq $serial)
        )
    })
    $media = 'UNKNOWN'
    if ($pd.Count -eq 1) {
        $mt = [string]$pd[0].MediaType
        if (@('HDD','3') -contains $mt) { $media = 'HDD' }
        if (@('SSD','4') -contains $mt) { $media = 'SSD' }
    }
    $volumes = @()
    foreach ($p in @($partitions | Where-Object { $_.DiskNumber -eq $disk.Number })) {
        $partitionVolumes = @()
        foreach ($access in @($p.AccessPaths)) {
            if (([string]$access).StartsWith('\\?\Volume{')) { $partitionVolumes += [string]$access }
        }
        if (-not $disk.IsOffline -and ([string]$p.DriveLetter) -match '^[A-Za-z]$' -and $partitionVolumes.Count -eq 0) {
            throw 'Volume montato senza percorso identificabile: rilevamento incompleto.'
        }
        $volumes += $partitionVolumes
    }
    $reasons = @()
    if ($protected.ContainsKey([int]$disk.Number)) { $reasons = @($protected[[int]$disk.Number] | Select-Object -Unique) }
    $rows += [pscustomobject]@{
        Number = [int]$disk.Number; Model = [string]$disk.FriendlyName;
        Serial = $serial; UniqueId = $unique; Size = [long]$disk.Size;
        SectorSize = [int]$disk.LogicalSectorSize; Bus = [string]$disk.BusType;
        Kind = $media; Protected = $reasons; Volumes = @($volumes | Select-Object -Unique);
        ReadOnly = [bool]$disk.IsReadOnly; Offline = [bool]$disk.IsOffline
    }
}
[pscustomobject]@{ ProtectionOK = $true; Disks = @($rows) } | ConvertTo-Json -Depth 6 -Compress
'''


def _strings(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Elenco di testo non valido nel rilevamento.")
    return tuple(value)


def parse_inventory(payload: dict) -> Inventory:
    if not isinstance(payload, dict) or payload.get("ProtectionOK") is not True:
        raise ValueError("Protezione del sistema non confermata.")
    raw = payload.get("Disks")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ValueError("Nessun disco rilevato dal sistema.")
    disks = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Informazioni di disco non valide.")
        for flag in ("ReadOnly", "Offline"):
            if not isinstance(item.get(flag), bool):
                raise ValueError("Stato del disco mancante o non valido.")
        kind = str(item.get("Kind", "UNKNOWN"))
        if kind not in ("HDD", "SSD", "UNKNOWN"):
            kind = "UNKNOWN"
        disks.append(Disk(
            number=int(item["Number"]), model=str(item["Model"]).strip(),
            serial=str(item.get("Serial", "")).strip(),
            unique_id=str(item.get("UniqueId", "")).strip(),
            size=int(item["Size"]), sector_size=int(item["SectorSize"]),
            bus=str(item["Bus"]), kind=kind,
            media_evidence="Windows Storage / Get-PhysicalDisk" if kind != "UNKNOWN" else "",
            protected_reasons=_strings(item.get("Protected")),
            volume_paths=_strings(item.get("Volumes")),
            read_only=item["ReadOnly"], offline=item["Offline"],
            transport_serial=str(item.get("Serial", "")).strip(), identity_source="WINDOWS",
            transport_model=str(item["Model"]).strip()))
    numbers = [disk.number for disk in disks]
    if len(set(numbers)) != len(numbers) or any(number < 0 for number in numbers):
        raise ValueError("Numerazione dei dischi ambigua.")
    if not any(disk.protected for disk in disks):
        raise ValueError("Nessuna unità protetta: rilevamento incompleto.")
    return Inventory(tuple(sorted(disks, key=lambda disk: disk.number)), True)


def powershell(script: str, env: dict | None = None, timeout: int = 45) -> str:
    if os.name != "nt":
        raise RuntimeError("Il rilevamento reale è disponibile solo su Windows.")
    # The executable is a trusted OS path, not an executable discovered on PATH.
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    executable = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    completed = subprocess.run(
        [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout, creationflags=0x08000000, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Rilevamento Windows non riuscito.")
    return completed.stdout.lstrip("\ufeff").strip()


class WindowsInventory:
    def __init__(self, app_path: Path, report_path: Path):
        self.app_path = app_path.resolve()
        self.report_path = report_path.resolve()

    def scan(self) -> Inventory:
        try:
            env = os.environ.copy()
            env.update(DEJAVU_APP_PATH=str(self.app_path),
                       DEJAVU_RUNTIME_PATH=str(Path(sys.executable).resolve()),
                       DEJAVU_REPORT_PATH=str(self.report_path))
            payload = json.loads(powershell(INVENTORY_SCRIPT, env))
            inventory = parse_inventory(payload)
            # Read-only native probes. Unknown drives are never assumed to be HDDs.
            from .windows_io import inspect_disk
            enriched = []
            for disk in inventory.disks:
                if disk.protected:
                    enriched.append(disk)
                    continue
                try:
                    info = inspect_disk(disk.number)
                    if (info["size"] != disk.size or info["number"] != disk.number
                            or info["sector_size"] != disk.sector_size):
                        enriched.append(replace(disk, kind="UNKNOWN",
                                                media_evidence="Identità, capacità o settori incoerenti"))
                        continue
                    native_kind = info["kind"]
                    kind = disk.kind
                    evidence = disk.media_evidence
                    if native_kind != "UNKNOWN":
                        if kind not in ("UNKNOWN", native_kind):
                            kind, evidence = "UNKNOWN", "Indicazioni del tipo in conflitto"
                        else:
                            kind, evidence = native_kind, info["evidence"]
                    serial = disk.serial or info["serial"]
                    model = disk.model
                    source, firmware_model = "WINDOWS", ""
                    if info.get("serial_source") == "ATA":
                        firmware_model = info.get("firmware_model", "")
                        # A SATA bridge may expose its own generic product name
                        # and serial for every bay. IDENTIFY was issued on this
                        # PhysicalDrive handle; number/size/sector were checked
                        # above. Keep the enclosure identifiers as metadata and
                        # use the actual drive's model and unique firmware serial.
                        # A non-generic, conflicting drive model stays blocked.
                        usb_model = norm(disk.model)
                        model_matches = norm(firmware_model) == usb_model
                        generic_bridge = "SATABRIDGE" in usb_model
                        if (disk.bus == "USB" and info.get("bus_type") == 7
                                and firmware_model and usable_serial(info["serial"])
                                and (model_matches or generic_bridge)
                                and info["kind"] in ("HDD", "SSD")):
                            serial, source = info["serial"], "ATA"
                            if kind in ("HDD", "SSD"):
                                model = firmware_model
                        elif not usable_serial(info["serial"]):
                            kind, evidence = "UNKNOWN", "IDENTIFY senza numero di serie valido del disco"
                        elif disk.bus == "USB" and info.get("bus_type") != 7:
                            kind, evidence = "UNKNOWN", "Identità ATA e collegamento USB non coerenti"
                        elif disk.serial and norm(disk.serial) != norm(info["serial"]):
                            kind, evidence = "UNKNOWN", "Identità ATA non associabile con certezza al disco Windows"
                        elif disk.bus != "USB":
                            serial, source = info["serial"], "ATA"
                        elif not firmware_model or norm(firmware_model) != norm(disk.model):
                            kind, evidence = "UNKNOWN", "Modello ATA e modello Windows non corrispondenti"
                    elif disk.serial and info["serial"] and norm(disk.serial) != norm(info["serial"]):
                        kind, evidence = "UNKNOWN", "Numero di serie incoerente"
                    enriched.append(replace(disk, model=model, serial=serial, kind=kind,
                                            media_evidence=evidence, identity_source=source,
                                            firmware_model=firmware_model,
                                            firmware_serial=info["serial"] if info.get("serial_source") == "ATA" else "",
                                            identify_transport=info.get("identify_transport", ""),
                                            firmware_revision=info.get("firmware_revision", ""),
                                            native_methods=tuple(info.get("native_methods", ())),
                                            security_state=tuple(info.get("security_state", ())),
                                            enhanced_erase_minutes=info.get("enhanced_erase_minutes", 0),
                                            probe_notes=tuple(info.get("probe_notes", ()))))
                except Exception as error:
                    enriched.append(replace(disk, probe_notes=("Interrogazione nativa non riuscita: " + str(error),)))
            return replace(inventory, disks=tuple(enriched))
        except Exception as error:
            return Inventory((), False, str(error))
