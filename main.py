"""Entry point; demo mode cannot instantiate the Windows disk backend."""
from __future__ import annotations

import argparse
import configparser
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

from dejavu import __version__
from dejavu.windows_process import APP_MUTEX, InstanceBusy, WindowsInstance, enable_dpi_awareness


def program_path():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()


def data_folder():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path.home() / ".local" / "share"
    return base / "CrederePerVedere" / "DejavuDiskTool"


def alert(title, message):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, message, parent=root)
    root.destroy()


def elevate():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return True
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                    ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    args = sys.argv[1:] if getattr(sys, "frozen", False) else [str(program_path()), *sys.argv[1:]]
    result = shell.ShellExecuteW(None, "runas", sys.executable,
                                subprocess.list2cmdline(args), str(program_path().parent), 1)
    if (result or 0) <= 32:
        alert("Avvio non riuscito", "Windows non ha autorizzato l'avvio come amministratore.\n"
              "Per la modalità reale sono necessari i permessi di amministratore.")
    return False


def load_concurrency(path=None):
    path = path if path is not None else program_path().parent / "impostazioni.ini"
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    concurrency = parser.getint("lavoro", "dischi_contemporanei", fallback=2)
    if not 1 <= concurrency <= 8:
        raise ValueError("In impostazioni.ini, dischi_contemporanei deve essere tra 1 e 8.")
    return concurrency


def main(argv=None):
    enable_dpi_awareness()
    parser = argparse.ArgumentParser(description="Dejavu DiskTool: cancellazione HDD e SSD SATA")
    parser.add_argument("--demo", action="store_true", help="Interfaccia con soli file di prova, nessun accesso ai dischi fisici")
    parser.add_argument("--diagnostics", action="store_true", help="Rilevamento in sola lettura, esportato in JSON")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--impostazioni", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--recupera-ssd", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--disco", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--conferma", help=argparse.SUPPRESS)
    parser.add_argument("--rimozione-usb-interna", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.rimozione_usb_interna:
        if args.demo or args.diagnostics or args.recupera_ssd:
            parser.error("La rimozione interna non ammette altre modalità.")
        from dejavu.usb_removal import helper_main
        return helper_main(args.rimozione_usb_interna)
    if args.recupera_ssd and (args.demo or args.diagnostics or args.disco is None or not args.conferma):
        parser.error("Recupero SSD: indicare --disco e --conferma, senza altre modalità.")
    if not args.demo:
        if os.name != "nt":
            print("La modalità reale richiede Windows. Usa --demo per la simulazione.", file=sys.stderr)
            return 2
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            alert("Sistema non supportato", "Usa Windows e Python a 64 bit.")
            return 2
        if not elevate():
            return 0
    try:
        with WindowsInstance(APP_MUTEX):
            return run_application(args)
    except InstanceBusy as error:
        alert("Programma già aperto", str(error))
        return 0


def run_application(args):
    folder = data_folder()
    reports = folder / ("rapporti_demo" if args.demo else "rapporti")
    reports.mkdir(parents=True, exist_ok=True)
    if args.demo:
        from dejavu.simulation import DemoBackend
        backend = DemoBackend()
    else:
        from dejavu.backend import WindowsBackend
        backend = WindowsBackend(program_path(), reports)
    if args.recupera_ssd:
        from dejavu.ssd import recover_security
        inventory = backend.scan()
        disk = next((d for d in inventory.disks if d.number == args.disco), None)
        if disk is None:
            raise ValueError("SSD da recuperare non rilevato.")
        message = recover_security(disk, inventory, args.recupera_ssd, args.conferma)
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Recupero password SSD", message, parent=root)
        root.destroy()
        return 0
    if args.diagnostics:
        from dejavu.diagnostics import build_payload
        from dejavu.reports import atomic_text
        inventory = backend.scan()
        path = folder / ("diagnostica_demo.json" if args.demo else "diagnostica_windows.json")
        atomic_text(path, json.dumps(build_payload(inventory), ensure_ascii=False, indent=2))
        if args.demo:
            backend.cleanup()
        if os.name == "nt":
            os.startfile(str(path))
        else:
            print(path)
        return 0 if inventory.protection_ok else 1
    from dejavu.gui import Application
    root = tk.Tk()
    Application(root, backend, reports, load_concurrency(args.impostazioni), args.demo)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        if "--rimozione-usb-interna" in sys.argv:
            raise SystemExit(1)
        try:
            from traceback import format_exc
            folder = data_folder()
            folder.mkdir(parents=True, exist_ok=True)
            log = folder / "errore_avvio.txt"
            log.write_text(format_exc(), encoding="utf-8")
            alert("Avvio non riuscito", f"{error}\n\nDettagli salvati in:\n{log}")
        except Exception:
            print(f"Avvio non riuscito: {error}", file=sys.stderr)
        raise SystemExit(1)
