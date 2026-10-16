"""Read-only metadata report. No volume locking, offline changes or writes."""
from dataclasses import asdict
import json
import platform

from . import __version__
from .inventory import powershell


PNP_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$osInfo = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
$rows = @()
foreach ($drive in @(Get-CimInstance Win32_DiskDrive -ErrorAction Stop)) {
    $nodes = @()
    $notes = @()
    $id = [string]$drive.PNPDeviceID
    if (Get-Command Get-PnpDeviceProperty -ErrorAction SilentlyContinue) {
        for ($level=0; $level -lt 8 -and $id -ne ''; $level++) {
            $name = ''
            try { $name = [string](Get-PnpDevice -InstanceId $id -ErrorAction Stop).FriendlyName } catch { }
            $nodes += [pscustomobject]@{ InstanceId=$id; Name=$name }
            try {
                $parent = Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_Parent' -ErrorAction Stop
                $next = [string]$parent.Data
                if ($next -eq $id) { break }
                $id = $next
            } catch { $notes += $_.Exception.Message; break }
        }
    } else { $notes += 'Get-PnpDeviceProperty non disponibile.' }
    $rows += [pscustomobject]@{
        Number=[int]$drive.Index; Model=[string]$drive.Model;
        Serial=[string]$drive.SerialNumber; PnpDeviceId=[string]$drive.PNPDeviceID;
        InterfaceType=[string]$drive.InterfaceType; Nodes=@($nodes); Notes=@($notes)
    }
}
[pscustomobject]@{
    Windows=[pscustomobject]@{ Caption=[string]$osInfo.Caption; Version=[string]$osInfo.Version; Build=[string]$osInfo.BuildNumber };
    Devices=@($rows)
} | ConvertTo-Json -Depth 8 -Compress
'''


def build_payload(inventory, include_pnp=True):
    payload = asdict(inventory)
    payload.update(application="Dejavu DiskTool", version=__version__,
                   python=platform.python_version(), operation="Rilevamento senza cancellazione")
    if include_pnp and not inventory.simulated:
        try:
            payload["windows_devices"] = json.loads(powershell(PNP_SCRIPT, timeout=45))
        except Exception as error:
            payload["windows_devices_error"] = str(error)
    return payload
