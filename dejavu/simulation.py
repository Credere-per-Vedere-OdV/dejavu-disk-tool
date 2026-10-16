"""An isolated file backend for demonstrations and meaningful I/O tests."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile
import time

from .core import Blocked, Disk, Inventory


class FileSession:
    def __init__(self, path: Path, fail_read: bool = False, delay: float = 0):
        self.path, self.fail_read, self.delay = path, fail_read, delay
        self.size = path.stat().st_size
        self.warnings = []
        self.file = None

    def __enter__(self):
        # r+b never truncates a target just by opening it.
        self.file = self.path.open("r+b", buffering=0)
        return self

    def __exit__(self, *args):
        if self.file is not None:
            self.file.close()
        return False

    def write(self, data: bytes) -> int:
        if self.delay:
            time.sleep(self.delay)
        return self.file.write(data)

    def read(self, size: int) -> bytes:
        if self.delay:
            time.sleep(self.delay)
        if self.fail_read:
            raise IOError("Errore di lettura simulato: collegamento interrotto.")
        return self.file.read(size)

    def flush(self):
        self.file.flush()
        os.fsync(self.file.fileno())

    def rewind(self):
        self.file.seek(0)

    def finish(self):
        pass


class DemoBackend:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dejavu-demo-")
        self.root = Path(self.temp.name)
        self.disks = (
            Disk(0, "Windows — esempio protetto", "DEMO-SYSTEM", "DEMO-0",
                 512 * 10**9, 512, "SATA", "SSD", "Simulazione",
                 ("Windows in esecuzione",), simulated=True),
            Disk(1, "HDD SATA — esempio", "DEMO-HDD-001", "DEMO-1",
                 16 * 1024**2, 512, "SATA", "HDD", "Simulazione", simulated=True),
            Disk(2, "HDD USB — esempio", "DEMO-HDD-002", "DEMO-2",
                 24 * 1024**2, 4096, "USB", "HDD", "Simulazione", simulated=True),
            Disk(3, "SSD — esempio", "DEMO-SSD-003", "DEMO-3",
                 8 * 1024**2, 512, "USB", "SSD", "Simulazione", simulated=True,
                 identity_source="ATA", firmware_model="SSD — esempio",
                 native_methods=("ATA_SANITIZE_BLOCK",)),
            Disk(4, "HDD con errore — esempio", "DEMO-HDD-004", "DEMO-4",
                 16 * 1024**2, 512, "SATA", "HDD", "Simulazione", simulated=True),
        )
        self.paths = {}
        for disk in self.disks[1:]:
            path = self.root / f"demo-{disk.number}.bin"
            with path.open("wb") as output:
                for _ in range(disk.size // (1024**2)):
                    output.write(bytes([0xA5]) * (1024**2))
            self.paths[disk.number] = path

    def scan(self) -> Inventory:
        return Inventory(self.disks, True, simulated=True)

    def open_session(self, disk: Disk) -> FileSession:
        if not disk.simulated or disk.number not in self.paths:
            raise Blocked("Il backend demo accetta soltanto i propri file di prova.")
        path = self.paths[disk.number].resolve()
        if path.parent != self.root.resolve() or not path.is_file():
            raise Blocked("File di simulazione non valido.")
        if disk.kind == "SSD":
            return DemoSsdSession(path)
        return FileSession(path, fail_read=disk.number == 4, delay=0.35)

    def cleanup(self):
        self.temp.cleanup()


class DemoSsdSession(FileSession):
    method = "SIMULAZIONE SSD: ATA Sanitize Block Erase"

    def __init__(self, path):
        super().__init__(path)
        self.native_details = {"completion": "not_started", "simulated": True}

    def sanitize(self, cancel, emit):
        from .core import Cancelled
        if cancel.is_set():
            raise Cancelled("Simulazione interrotta prima della sanitizzazione.")
        for percent in (5, 30, 60, 90):
            emit({"native": True, "percent": percent, "phase": "Simulazione SSD",
                  "message": "Stato del controller simulato; nessun dispositivo reale interrogato."})
            time.sleep(.20)
        self.file.write(bytes([0xFF]) * self.size)
        self.flush()
        self.native_details["completion"] = "device_confirmed"
        emit({"native": True, "percent": 100, "phase": "Simulazione SSD", "message": "Simulazione completata."})
