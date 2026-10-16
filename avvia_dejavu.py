"""Stable Windows launcher: updates before elevation, waits through the whole job."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Event, Thread
import tkinter as tk
from tkinter import messagebox, ttk

from dejavu.resources import asset_path
from dejavu.updater import UpdateManager, append_log
from dejavu.update_protocol import json_object
from dejavu.windows_process import (APP_MUTEX, LAUNCHER_MUTEX, InstanceBusy,
                                    WindowsInstance, enable_dpi_awareness,
                                    run_elevated_and_wait)


def show_error(message):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Dejavu · Avvio", message, parent=root)
    root.destroy()


def prepare(manager, log, skip_update=False):
    """No worker touches Tk. A cancelled window never launches the eraser."""
    root = tk.Tk()
    root.title("Dejavu · Avvio")
    root.geometry("540x170")
    root.resizable(False, False)
    root.configure(bg="white")
    tk.Label(root, text="Dejavu Disk Tool", bg="white", fg="#0d6f70",
             font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=24, pady=(20, 10))
    label = tk.Label(root, text="Controllo degli aggiornamenti…", bg="white", fg="#172b40",
                     font=("Segoe UI", 10), wraplength=490, justify="left")
    label.pack(anchor="w", padx=24)
    bar = ttk.Progressbar(root, mode="indeterminate")
    bar.pack(fill="x", padx=24, pady=18)
    bar.start(20)
    cancelled, messages = Event(), Queue()
    manager.cancelled = cancelled.is_set
    manager.http.cancelled = cancelled.is_set
    result = {}

    def worker():
        try:
            version, executable = manager.current()
            result.update(version=version, executable=executable, changed=False)
            if not skip_update:
                try:
                    candidate = manager.check()
                    if candidate:
                        manager.install(candidate, lambda text: messages.put(("status", text)))
                        version, executable = manager.current()
                        result.update(version=version, executable=executable, changed=True)
                        append_log(log, f"Aggiornata la versione {version}.")
                    else:
                        messages.put(("status", "Versione già aggiornata. Avvio…"))
                except Exception as error:
                    append_log(log, f"Aggiornamento non applicato: {type(error).__name__}: {error}")
                    # An interrupted check/install must not cause an unintended
                    # launch. Other update failures leave the installed version.
                    if not cancelled.is_set():
                        messages.put(("status", "Aggiornamento non disponibile. Avvio della versione installata…"))
            messages.put(("done", None))
        except Exception as error:
            result["error"] = str(error)
            messages.put(("done", None))

    def close():
        cancelled.set()
        result["cancelled"] = True
        bar.stop()
        root.destroy()

    def finish():
        bar.stop()
        root.destroy()

    def poll():
        latest = None
        done = False
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == "done":
                    done = True
                else:
                    latest = value
        except Empty:
            pass
        if latest:
            label.configure(text=latest)
        if done:
            root.after(450, finish)
        else:
            root.after(80, poll)

    root.protocol("WM_DELETE_WINDOW", close)
    Thread(target=worker, daemon=True).start()
    root.after(80, poll)
    root.mainloop()
    if result.get("cancelled") or cancelled.is_set():
        return None
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def main():
    parser = argparse.ArgumentParser(description="Avviatore con aggiornamenti di Dejavu Disk Tool")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--senza-aggiornamenti", action="store_true", help="Avvio tecnico della versione già installata")
    args = parser.parse_args()
    enable_dpi_awareness()
    if os.name != "nt" or not getattr(sys, "frozen", False):
        print("Questo avviatore si usa nel pacchetto EXE Windows. Per i sorgenti usare main.py.", file=sys.stderr)
        return 2
    installation = Path(sys.executable).resolve().parent
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    log = base / "CrederePerVedere" / "DejavuDiskTool" / "aggiornamenti.log"
    try:
        with WindowsInstance(LAUNCHER_MUTEX):
            # A main executable started directly also has this mutex. Probe
            # before downloading anything; it is held by main throughout a job.
            with WindowsInstance(APP_MUTEX):
                pass
            config = json_object(asset_path("aggiornamenti.json").read_bytes())
            key = asset_path("update_public_key.pem").read_bytes()
            manager = UpdateManager(installation, config, key)
            prepared = prepare(manager, log, args.senza_aggiornamenti)
            if prepared is None:
                return 0
            arguments = ["--impostazioni", str(installation / "impostazioni.ini")]
            if args.demo:
                arguments.append("--demo")
            if args.diagnostics:
                arguments.append("--diagnostics")
            code = run_elevated_and_wait(prepared["executable"], arguments, elevate=not args.demo)
            if code:
                append_log(log, f"La versione {prepared['version']} è terminata con codice {code}.")
                if prepared["changed"] and manager.rollback(prepared["version"]):
                    show_error("La nuova versione si è chiusa con un errore.\n"
                               "La versione precedente sarà usata al prossimo avvio.\n"
                               "Controllare gli esiti dei dischi e il registro di avvio prima di riprovare.")
            return code
    except InstanceBusy as error:
        show_error(str(error))
        return 0
    except OSError as error:
        if getattr(error, "winerror", None) == 1223:
            return 0  # User declined UAC; this is not a failed app version.
        append_log(log, f"Errore di avvio: {type(error).__name__}: {error}")
        show_error(f"{error}\n\nRegistro: {log}")
        return 1
    except Exception as error:
        append_log(log, f"Errore di avvio: {type(error).__name__}: {error}")
        show_error(f"{error}\n\nRegistro: {log}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
