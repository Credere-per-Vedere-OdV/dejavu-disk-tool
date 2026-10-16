"""Complete non-GUI demo. This script can only wipe its owned demo files."""
from pathlib import Path
from threading import Event
import argparse

from dejavu.engine import run_batch
from dejavu.simulation import DemoBackend


def main():
    parser = argparse.ArgumentParser(description="Simulazione con soli file temporanei")
    parser.add_argument("--rapporti", type=Path, default=Path("esempi_rapporti"))
    args = parser.parse_args()
    backend = DemoBackend()
    try:
        inventory = backend.scan()
        targets = [disk for disk in inventory.disks if not disk.protected]
        def emit(event):
            if event["type"] == "result":
                result = event["result"]
                print(f"Disco simulato {result.disk.number}: {result.status} · {result.message}")
        results, reports = run_batch(targets, inventory, backend, Event(), emit, args.rapporti, 2)
        expected = {1: "SUCCESS", 2: "SUCCESS", 3: "SUCCESS", 4: "FAILED"}
        if {result.disk.number: result.status for result in results} != expected or reports is None:
            raise RuntimeError("Simulazione con esito inatteso")
        print("SIMULAZIONE completata: due HDD e uno SSD riusciti, un errore di lettura HDD.")
        print("Rapporto:", reports[0].resolve())
    finally:
        backend.cleanup()


if __name__ == "__main__":
    main()
