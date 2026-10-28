from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event
from datetime import datetime
import ctypes
import os
import uuid

from .core import JobResult, run_job
from .reports import save_disk_record, save_reports


class KeepAwake:
    def __init__(self, simulated=False):
        self.simulated = simulated
        self.active = False

    def __enter__(self):
        if os.name == "nt" and not self.simulated:
            function = ctypes.WinDLL("kernel32", use_last_error=True).SetThreadExecutionState
            function.argtypes = [ctypes.c_uint32]
            function.restype = ctypes.c_uint32
            self.function = function
            if not function(0x80000000 | 0x00000001):
                raise OSError("Impossibile mantenere il PC attivo durante il lavoro.")
            self.active = True
        return self

    def __exit__(self, *args):
        if self.active:
            self.function(0x80000000)
        return False


def run_batch(disks, inventory, backend, cancel: Event, emit, report_folder: Path,
              concurrency: int = 2):
    results = []
    disk_records, record_errors = [], []
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]

    def collect(result):
        results.append(result)
        try:
            disk_records.append(save_disk_record(report_folder, result, batch_id))
        except Exception as error:
            record_errors.append(f"Disco {result.disk.number}: {error}")

    try:
        concurrency = max(1, min(8, int(concurrency)))
        with KeepAwake(inventory.simulated):
            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="dejavu") as pool:
                futures = [pool.submit(run_job, disk, backend.scan,
                                       backend.open_session, cancel, emit)
                           for disk in disks]
                for future in as_completed(futures):
                    collect(future.result())
    except Exception as error:
        recorded = {result.disk.number for result in results}
        for disk in disks:
            if disk.number not in recorded:
                result = JobResult(disk, "BLOCKED", str(error))
                collect(result)
                emit({"type": "result", "number": disk.number, "result": result})
    report_error, paths = "", None
    try:
        paths = save_reports(report_folder, inventory, results, concurrency, batch_id=batch_id)
    except Exception as error:
        report_error = f"Gli esiti sono visibili, ma il rapporto non è stato salvato: {error}"
    if record_errors:
        report_error += ("\n" if report_error else "") + "Registri delle singole unità non salvati: " + " | ".join(record_errors)

    # All futures have joined and all sessions have closed. Save the erasure
    # evidence BEFORE attempting any USB safe removal. Erasure outcomes are
    # immutable here; removal has its own independent outcome in the report.
    removal_results = []
    usb_numbers = [result.disk.number for result in results if result.disk.bus == "USB"]
    if usb_numbers:
        from .usb_removal import outcome
        emit({"type": "finalizing", "message": "Cancellazioni terminate. Controllo della rimozione sicura USB…"})
        if report_error or not paths:
            removal_results = [outcome(usb_numbers, "SKIPPED", "Rapporti non completamente salvati: rimozione automatica esclusa.")]
        elif cancel.is_set():
            removal_results = [outcome(usb_numbers, "SKIPPED", "Lotto interrotto: rimozione automatica esclusa.")]
        elif inventory.simulated:
            removal_results = [outcome(usb_numbers, "SIMULATED", "Simulazione: nessuna docking fisica è stata espulsa.")]
        else:
            try:
                remove = getattr(backend, "remove_completed", None)
                if not callable(remove):
                    removal_results = [outcome(usb_numbers, "SKIPPED", "Rimozione automatica USB non disponibile in questo ambiente.")]
                else:
                    with KeepAwake(False):
                        removal_results = remove(results, cancel)
            except Exception as error:
                removal_results = [outcome(usb_numbers, "NOT_CONFIRMED", "Rimozione USB non confermata: " + str(error))]
        if paths:
            try:
                paths = save_reports(report_folder, inventory, results, concurrency,
                                     batch_id=batch_id, safe_removal=removal_results)
            except Exception as error:
                report_error += ("\n" if report_error else "") + "Esito della rimozione USB non salvato nel rapporto: " + str(error)
    emit({"type": "batch_done", "results": results, "reports": paths,
          "report_error": report_error, "disk_records": tuple(disk_records), "batch_id": batch_id,
          "removal_results": removal_results})
    return results, paths
