"""Policy and target validation for HDD overwrite and native SATA SSD erase.

HDD success requires complete write, flush and readback. SSD success requires
the dedicated session's native completion checks. OS-specific I/O is separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from threading import Event
from typing import Callable, Protocol
import time


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(value: str) -> str:
    return "".join(str(value).split()).upper()


@dataclass(frozen=True)
class Disk:
    number: int
    model: str
    serial: str
    unique_id: str
    size: int
    sector_size: int
    bus: str
    kind: str = "UNKNOWN"
    media_evidence: str = ""
    protected_reasons: tuple[str, ...] = ()
    volume_paths: tuple[str, ...] = ()
    read_only: bool = False
    offline: bool = False
    simulated: bool = False
    transport_serial: str = ""
    identity_source: str = ""
    firmware_model: str = ""
    probe_notes: tuple[str, ...] = ()
    firmware_revision: str = ""
    native_methods: tuple[str, ...] = ()
    security_state: tuple[str, ...] = ()
    enhanced_erase_minutes: int = 0

    @property
    def key(self) -> tuple:
        # Windows disk numbers alone are not persistent identities.
        return (self.number, norm(self.serial), norm(self.unique_id),
                norm(self.model), self.size, self.sector_size, self.bus,
                self.identity_source, norm(self.firmware_model),
                self.firmware_revision, self.native_methods, self.security_state)

    @property
    def protected(self) -> bool:
        return bool(self.protected_reasons)


@dataclass(frozen=True)
class Inventory:
    disks: tuple[Disk, ...]
    protection_ok: bool
    error: str = ""
    scanned_at: str = field(default_factory=stamp)
    simulated: bool = False


class Blocked(Exception):
    """A target must not be written."""


class Cancelled(Exception):
    pass


def validate_target(selected: Disk, fresh: Inventory) -> Disk:
    if not fresh.protection_ok or fresh.error:
        raise Blocked("Impossibile confermare la protezione delle unità in uso. "
                      + (fresh.error or "Rilevamento del sistema incompleto."))
    numbers = [d.number for d in fresh.disks]
    if len(numbers) != len(set(numbers)):
        raise Blocked("Rilevamento ambiguo: numeri di disco duplicati.")
    current = next((d for d in fresh.disks if d.number == selected.number), None)
    if current is None:
        raise Blocked("Disco scollegato: collegarlo e ripetere la selezione.")
    if current.key != selected.key:
        raise Blocked("Il disco è cambiato dalla selezione: ripetere il rilevamento.")
    if current.protected:
        raise Blocked("Unità protetta: " + "; ".join(current.protected_reasons))
    if current.read_only:
        raise Blocked("Disco di sola lettura: nessuna modifica eseguita.")
    if current.size <= 0 or current.sector_size not in (512, 4096):
        raise Blocked("Capacità o dimensione dei settori non supportata.")
    if current.size % current.sector_size:
        raise Blocked("La capacità non corrisponde a un numero intero di settori.")
    if not norm(current.serial):
        raise Blocked("Numero di serie non disponibile: identità insufficiente.")
    if sum(norm(d.serial) == norm(current.serial) for d in fresh.disks) > 1:
        raise Blocked("Numero di serie duplicato: impossibile distinguere le unità.")
    if current.bus in ("RAID", "Virtual", "StorageSpaces", "FileBackedVirtual"):
        raise Blocked("Unità virtuale o aggregata: cancellazione diretta non supportata.")
    if current.kind == "SSD":
        if (current.bus not in ("SATA", "ATA", "USB")
                or current.identity_source != "ATA" or not current.firmware_model):
            raise Blocked("SSD SATA non identificato con certezza: nessuna cancellazione.")
        methods = set(current.native_methods)
        if not methods.intersection(("ATA_SANITIZE_BLOCK", "ATA_SECURITY_ENHANCED")):
            raise Blocked("SSD senza procedura nativa supportata: affidarlo al responsabile tecnico.")
        if "ATA_SANITIZE_BLOCK" not in methods and current.security_state:
            raise Blocked("Sicurezza ATA dello SSD non disponibile: " + ", ".join(current.security_state))
        return current
    if current.kind != "HDD":
        raise Blocked("Tipo di unità non riconosciuto con certezza: nessuna scrittura.")
    if current.bus == "USB" and not current.simulated and (
            current.identity_source != "ATA" or not current.firmware_model):
        raise Blocked("Il collegamento USB non ha confermato l'identità del disco tramite IDENTIFY. "
                      "Gli identificativi del solo collegamento non bastano per iniziare.")
    return current


class Session(Protocol):
    size: int
    warnings: list[str]
    def __enter__(self) -> "Session": ...
    def __exit__(self, *args) -> bool | None: ...
    def write(self, data: bytes) -> int: ...
    def read(self, size: int) -> bytes: ...
    def flush(self) -> None: ...
    def rewind(self) -> None: ...
    def finish(self) -> None: ...


@dataclass
class JobResult:
    disk: Disk
    status: str
    message: str
    written: int | None = 0
    verified: int | None = 0
    started_at: str = field(default_factory=stamp)
    finished_at: str = ""
    duration_seconds: float = 0
    method: str = "HDD Clear: 1 sovrascrittura con zeri + rilettura integrale"
    coverage: str = "Spazio indirizzabile esposto al computer; nessuna attestazione Purge"
    warnings: list[str] = field(default_factory=list)
    native_details: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.disk.kind == "SSD":
            self.written = self.verified = None
            self.method = "SSD: procedura nativa da confermare"
            self.coverage = "Operazione interna al controller; nessuna certificazione Purge"

    def to_dict(self) -> dict:
        return asdict(self)


def run_job(selected: Disk, scan: Callable[[], Inventory],
            open_session: Callable[[Disk], Session], cancel: Event,
            emit: Callable[[dict], None], block_size: int = 8 * 1024 * 1024) -> JobResult:
    result = JobResult(selected, "FAILED", "Operazione non completata.")
    start = time.monotonic()
    last_emit = 0.0
    session = None

    def check_cancel() -> None:
        if cancel.is_set():
            raise Cancelled("Interrotto: cancellazione e verifica non complete.")

    def progress(phase: str, force: bool = False) -> None:
        nonlocal last_emit
        now = time.monotonic()
        if force or now - last_emit >= 0.20:
            processed = result.written + result.verified
            percent = min(100, 100 * processed / (2 * selected.size))
            elapsed = now - start
            speed = processed / elapsed if elapsed > 0 else 0
            remaining = (2 * selected.size - processed) / speed if speed else None
            emit({"type": "progress", "number": selected.number, "phase": phase,
                  "percent": percent, "written": result.written,
                  "verified": result.verified, "speed": speed, "eta": remaining})
            last_emit = now

    try:
        check_cancel()
        emit({"type": "phase", "number": selected.number, "phase": "Controlli iniziali"})
        current = validate_target(selected, scan())
        if block_size <= 0 or block_size % current.sector_size:
            raise Blocked("Dimensione dei blocchi non allineata ai settori.")
        check_cancel()
        with open_session(current) as session:
            if session.size != current.size:
                raise Blocked("La capacità riletta dal dispositivo è cambiata.")
            if current.kind == "SSD":
                result.method = session.method
                result.native_details = session.native_details
                check_cancel()
                def native_progress(event):
                    emit({**event, "type": "progress", "number": selected.number})
                session.sanitize(cancel, native_progress)
                session.finish()
                result.status = "SUCCESS"
                result.message = "Sanitizzazione SSD completata; esito confermato dal dispositivo."
                return result
            zero_block = bytes(block_size)
            progress("Cancellazione", True)
            while result.written < current.size:
                check_cancel()
                requested = min(block_size, current.size - result.written)
                data = zero_block if requested == block_size else zero_block[:requested]
                offset = result.written
                count = session.write(data)
                if isinstance(count, int) and 0 < count <= requested:
                    result.written += count
                if count != requested:
                    raise IOError(f"Scrittura incompleta alla posizione {offset}: "
                                  f"{count} byte su {requested}.")
                progress("Cancellazione")
            session.flush()
            check_cancel()
            session.rewind()
            progress("Verifica", True)
            while result.verified < current.size:
                check_cancel()
                requested = min(block_size, current.size - result.verified)
                data = session.read(requested)
                if len(data) != requested:
                    raise IOError(f"Lettura incompleta alla posizione {result.verified}: "
                                  f"{len(data)} byte su {requested}.")
                expected = zero_block if requested == block_size else zero_block[:requested]
                if data != expected:
                    raise IOError(f"Verifica fallita alla posizione {result.verified}: "
                                  "il contenuto letto non corrisponde agli zeri scritti.")
                result.verified += requested
                progress("Verifica")
            check_cancel()
            session.finish()
        result.warnings = list(session.warnings)
        result.status = "SUCCESS"
        result.message = "Cancellazione e verifica complete."
        progress("Completato", True)
    except Blocked as error:
        result.status = "FAILED" if session is not None and getattr(session, "wrote", False) else "BLOCKED"
        result.message = str(error)
    except Cancelled as error:
        result.status, result.message = "CANCELLED", str(error)
    except Exception as error:
        result.status = "FAILED"
        result.message = f"Cancellazione non confermata: {error}"
    finally:
        if session is not None:
            result.warnings = list(session.warnings)
        result.finished_at = stamp()
        result.duration_seconds = round(time.monotonic() - start, 3)
        emit({"type": "result", "number": selected.number, "result": result})
    return result


def human_size(size: int) -> str:
    if size >= 10**12:
        return f"{size / 10**12:.2f} TB".replace(".", ",")
    if size >= 10**9:
        return f"{size / 10**9:.1f} GB".replace(".", ",")
    if size >= 10**6:
        return f"{size / 10**6:.1f} MB".replace(".", ",")
    return f"{size / 10**3:.1f} KB".replace(".", ",")


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "in calcolo"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {(seconds % 3600) // 60:02d} min"
