"""Real backend: enumeration and I/O share the same validated disk model."""
from pathlib import Path
from threading import Lock

from .inventory import WindowsInventory
from .windows_io import RawSession


class WindowsBackend:
    def __init__(self, app_path: Path, report_path: Path):
        self.inventory = WindowsInventory(app_path, report_path)
        self.scan_lock = Lock()
        self.recovery_folder = report_path.parent / "recupero_ssd"

    def scan(self):
        # Avoid concurrent PowerShell/native probe storms when several jobs start.
        with self.scan_lock:
            return self.inventory.scan()

    def open_session(self, disk):
        if disk.kind == "SSD":
            from .ssd import SsdSession
            return SsdSession(disk, self.recovery_folder)
        return RawSession(disk)
