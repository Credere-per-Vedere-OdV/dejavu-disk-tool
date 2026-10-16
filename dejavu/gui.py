"""Italian Tk interface. Workers never call Tk: events pass through a queue."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import os
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from . import __version__
from .core import Blocked, Inventory, human_duration, human_size, validate_target
from .engine import run_batch
from .reports import LABELS
from .branding import display_scale, logo_photo

BG = "#edf2f7"
INK = "#172b40"
MUTED = "#4c6274"
TEAL = "#0d6f70"
GREEN = "#146138"
RED = "#a03025"
AMBER = "#825800"
FONT = "Segoe UI" if os.name == "nt" else "Helvetica"


class DiskRow:
    def __init__(self, parent, disk, changed, protection_ok):
        self.disk = disk
        self.selected = tk.BooleanVar(value=False)
        self.frame = tk.Frame(parent, bg="white", padx=16, pady=12,
                              highlightthickness=1, highlightbackground="#d4dee8")
        self.frame.pack(fill="x", pady=(0, 8))
        self.frame.columnconfigure(1, weight=1)
        self.check = ttk.Checkbutton(self.frame, variable=self.selected, command=changed)
        self.check.grid(row=0, column=0, rowspan=3, padx=(0, 14), sticky="n", pady=6)
        if disk.protected or not protection_ok:
            self.check.state(["disabled"])
        tk.Label(self.frame, text=f"Disco {disk.number}   {disk.model or 'Modello non disponibile'}",
                 font=(FONT, 12, "bold"), bg="white", fg=INK,
                 anchor="w", wraplength=650, justify="left").grid(row=0, column=1, sticky="w")
        kind = {"HDD": "Disco meccanico", "SSD": "SSD", "UNKNOWN": "Tipo da verificare"}[disk.kind]
        tk.Label(self.frame, text=f"{human_size(disk.size)}  ·  {kind}  ·  {disk.bus}",
                 bg="white", fg=MUTED, anchor="w", font=(FONT, 10)).grid(row=1, column=1, sticky="w", pady=(3, 0))
        tk.Label(self.frame, text="Numero di serie: " + (disk.serial or "non disponibile"),
                 bg="white", fg=MUTED, anchor="w", font=(FONT, 10)).grid(row=2, column=1, sticky="w", pady=(3, 0))
        self.status = tk.Label(self.frame, text="", bg="white", fg=MUTED,
                               font=(FONT, 10, "bold"), anchor="w",
                               justify="left", wraplength=310)
        self.status.grid(row=0, column=2, rowspan=2, sticky="w", padx=(18, 0))
        self.progress = ttk.Progressbar(self.frame, mode="determinate", maximum=100, length=280)
        self.progress.grid(row=2, column=2, sticky="ew", padx=(18, 0))
        self.detail = tk.Label(self.frame, text="", bg="white", fg=MUTED,
                               font=(FONT, 10), anchor="w", justify="left", wraplength=940)
        self.detail.grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 0))
        if disk.protected:
            self.status.configure(text="PROTETTO", fg=MUTED)
            self.detail.configure(text="; ".join(disk.protected_reasons))
        elif disk.kind == "SSD":
            compatible = disk.identity_source == "ATA" and bool(disk.native_methods)
            self.status.configure(text="SSD SATA · procedura nativa" if compatible else "SSD · controllo nativo necessario",
                                  fg=TEAL if compatible else AMBER)
            self.detail.configure(text="Metodo e collegamento vengono verificati prima dell'avvio.")
        elif disk.kind == "UNKNOWN":
            self.status.configure(text="Tipo non confermato", fg=AMBER)
            self.detail.configure(text="La cancellazione sarà bloccata finché il tipo di disco non è identificato.")
        elif disk.read_only:
            self.status.configure(text="Sola lettura", fg=AMBER)
        elif not disk.serial:
            self.status.configure(text="Numero di serie non disponibile", fg=AMBER)
        else:
            self.status.configure(text="Pronto per la selezione")

    def set_enabled(self, enabled, protection_ok):
        allowed = enabled and protection_ok and not self.disk.protected
        self.check.state(["!disabled"] if allowed else ["disabled"])

    def phase(self, phase):
        self.status.configure(text=phase, fg=TEAL)

    def update_progress(self, event):
        if event.get("native"):
            percent = event.get("percent")
            if percent is None:
                if str(self.progress.cget("mode")) != "indeterminate":
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(20)
                self.phase(event["phase"])
            else:
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self.progress["value"] = percent
                self.phase(f"{event['phase']} · {percent:.0f}%")
            self.detail.configure(text=event.get("message", ""))
            return
        self.phase(f"{event['phase']} · {event['percent']:.0f}%")
        self.progress["value"] = event["percent"]
        self.detail.configure(text=f"Velocità: {human_size(int(event['speed']))}/s   ·   "
                                   f"Tempo rimanente: {human_duration(event['eta'])}")

    def finish(self, result):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        warning = result.status == "SUCCESS" and bool(result.warnings)
        color = AMBER if result.status == "BLOCKED" or warning else GREEN if result.status == "SUCCESS" else RED
        label = LABELS[result.status] + (" · CON AVVISI" if warning else "")
        if result.status == "SUCCESS" and result.disk.kind == "SSD":
            label = "SSD SANITIZZATO · ESITO CONFERMATO" + (" · CON AVVISI" if warning else "")
        self.status.configure(text=label, fg=color)
        self.detail.configure(text=result.message + (" " + " ".join(result.warnings) if result.warnings else ""))
        if result.status == "SUCCESS":
            self.progress["value"] = 100


class Application:
    def __init__(self, root, backend, report_folder: Path, concurrency=2, demo=False):
        self.root, self.backend = root, backend
        self.report_folder, self.concurrency, self.demo = report_folder, concurrency, demo
        self.events = Queue()
        self.cancel = Event()
        self.inventory = Inventory((), False)
        self.rows = {}
        self.busy = self.scanning = self.confirming = False
        self.have_results = False
        self.closing = False
        self.reports = None
        root.title("Dejavu · Cancellazione dischi" + (" · SIMULAZIONE" if demo else ""))
        self.display_scale = display_scale(root)
        width = min(round(1180 * self.display_scale), max(940, root.winfo_screenwidth() - 60))
        height = min(round(820 * self.display_scale), max(620, root.winfo_screenheight() - 110))
        root.geometry(f"{width}x{height}")
        root.minsize(min(round(900 * self.display_scale), root.winfo_screenwidth() - 40),
                     min(round(600 * self.display_scale), root.winfo_screenheight() - 80))
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        root.after(80, self._events)
        root.after(100, self.scan)
        root.after(15000, self._automatic_scan)

    def _build(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", font=(FONT, 11), padding=(12, 9))
        style.configure("Primary.TButton", background=TEAL, foreground="white", font=(FONT, 12, "bold"), padding=(18, 12))
        style.map("Primary.TButton", background=[("disabled", "#a6b4bd"), ("active", "#085555")])
        style.configure("Horizontal.TProgressbar", background=TEAL, troughcolor="#e0e8ef", thickness=10)
        header = tk.Frame(self.root, bg="white", padx=24, pady=14)
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)
        self.brand_images = []
        for column, name, max_width, max_height, fallback in (
                (0, "logo_cpv.png", 120, 120, "Credere per Vedere OdV"),
                (2, "logo_dejavu.png", 224, 104, "Progetto Dejavu")):
            try:
                logo = logo_photo(self.root, name, max_width * self.display_scale,
                                  max_height * self.display_scale)
                self.brand_images.append(logo)
                tk.Label(header, image=logo, bg="white").grid(row=0, column=column,
                    padx=(0, 16) if column == 0 else (16, 0))
            except (tk.TclError, OSError, ValueError):
                tk.Label(header, text=fallback, bg="white", fg=TEAL).grid(row=0, column=column)
        text_header = tk.Frame(header, bg="white")
        text_header.grid(row=0, column=1, sticky="ew")
        tk.Label(text_header, text="CREDERE PER VEDERE OdV", bg="white", fg=TEAL,
                 font=(FONT, 10, "bold")).pack(anchor="w")
        title = tk.Label(text_header, text="Cancellazione dischi", bg="white", fg=INK,
                         font=(FONT, 25, "bold"), anchor="w", justify="left", wraplength=500)
        title.pack(anchor="w", pady=(4, 4))
        subtitle = tk.Label(text_header, text="HDD e SSD SATA · Collega, seleziona e controlla gli esiti.",
                            bg="white", fg=MUTED, font=(FONT, 11), anchor="w", justify="left", wraplength=500)
        subtitle.pack(anchor="w")
        text_header.bind("<Configure>", lambda event: (title.configure(wraplength=max(180, event.width)),
                                                      subtitle.configure(wraplength=max(180, event.width))))
        tk.Frame(self.root, bg=TEAL, height=3).pack(fill="x")
        if self.brand_images:
            self.root.iconphoto(True, self.brand_images[0])
        if self.demo:
            tk.Label(self.root, text="SIMULAZIONE · vengono modificati soltanto piccoli file di prova",
                     bg="#e7e0fc", fg="#4b3478", font=(FONT, 11, "bold"), pady=9).pack(fill="x")
        body = tk.Frame(self.root, bg=BG, padx=24, pady=15)
        body.pack(fill="both", expand=True)
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Dischi rilevati", bg=BG, fg=INK, font=(FONT, 15, "bold")).pack(side="left")
        self.refresh = ttk.Button(top, text="Rileva dischi", command=lambda: self.scan(manual=True))
        self.refresh.pack(side="right")
        self.select_lot = ttk.Button(top, text="Seleziona lotto", command=self.select_batch, state="disabled")
        self.select_lot.pack(side="right", padx=(0, 10))
        self.connection = tk.Label(body, text="Rilevamento in corso…", bg=BG, fg=MUTED,
                                    anchor="w", justify="left", wraplength=1080, font=(FONT, 10))
        self.connection.pack(fill="x", pady=(0, 12))
        area = tk.Frame(body, bg=BG)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.list_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.list_window, width=event.width))
        self.root.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-event.delta / 120), "units"))
        policy_hint = tk.Label(body, text="Procedura automatica: HDD con verifica integrale; SSD SATA con cancellazione nativa. Unità in uso protette.",
                              bg=BG, fg=MUTED, font=(FONT, 10), anchor="w", justify="left", wraplength=1080)
        policy_hint.pack(side="bottom", fill="x", pady=(10, 0), before=area)
        body.bind("<Configure>", lambda event: (policy_hint.configure(wraplength=max(240, event.width - 48)),
                                                self.connection.configure(wraplength=max(240, event.width - 48))))
        footer = tk.Frame(self.root, bg="white", padx=26, pady=18)
        # Reserve action space before the expanding disk list, including on
        # short screens and with enlarged fonts.
        footer.pack(side="bottom", fill="x", before=body)
        actions = tk.Frame(footer, bg="white")
        actions.pack(side="right")
        self.open_button = ttk.Button(actions, text="Apri rapporto", command=self.open_report, state="disabled")
        self.open_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="Interrompi", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(0, 8))
        self.start_button = ttk.Button(actions, text="Avvia cancellazione", style="Primary.TButton", command=self.start, state="disabled")
        self.start_button.pack(side="left")
        self.summary = tk.Label(footer, text="Nessun disco selezionato", bg="white", fg=INK,
                                font=(FONT, 11, "bold"), anchor="w", justify="left", wraplength=470)
        self.summary.pack(side="left")
        tk.Label(self.root, text=f"Dejavu DiskTool {__version__} · {self.concurrency} dischi contemporaneamente · "
                 "Credere per Vedere OdV", bg=BG, fg=MUTED, font=(FONT, 9), pady=5).pack(side="bottom", fill="x", before=footer)

    def selected(self):
        return [row.disk for row in self.rows.values() if row.selected.get() and not row.disk.protected]

    def selection_changed(self):
        count = len(self.selected())
        self.summary.configure(text=f"{count} dischi selezionati" if count else "Seleziona i dischi da cancellare", fg=INK)
        self._controls()

    def eligible_rows(self):
        rows = []
        for row in self.rows.values():
            try:
                validate_target(row.disk, self.inventory)
            except Blocked:
                continue
            rows.append(row)
        return rows

    def select_batch(self):
        if self.busy or self.scanning or self.confirming or self.have_results:
            return
        eligible = self.eligible_rows()
        select = not eligible or not all(row.selected.get() for row in eligible)
        allowed = {row.disk.number for row in eligible}
        for row in self.rows.values():
            row.selected.set(select and row.disk.number in allowed)
            if select and row.disk.number not in allowed and not row.disk.protected:
                try:
                    validate_target(row.disk, self.inventory)
                except Blocked as error:
                    row.status.configure(text="ESCLUSO DAL LOTTO", fg=AMBER)
                    row.detail.configure(text=str(error))
        self.selection_changed()

    def _controls(self):
        active = not (self.busy or self.scanning or self.confirming)
        selectable = active and not self.have_results
        self.start_button.configure(state="normal" if selectable and self.inventory.protection_ok and self.selected() else "disabled")
        self.refresh.configure(state="normal" if active else "disabled")
        eligible = self.eligible_rows()
        all_selected = bool(eligible) and all(row.selected.get() for row in eligible)
        self.select_lot.configure(state="normal" if selectable and eligible else "disabled",
                                  text="Annulla selezione" if all_selected else "Seleziona lotto")
        for row in self.rows.values():
            row.set_enabled(selectable, self.inventory.protection_ok)

    def scan(self, manual=False):
        if self.busy or self.scanning or self.confirming or self.closing:
            return
        # Preserve completed outcomes until the operator requests a new list.
        if self.have_results and not manual:
            return
        if manual:
            self.have_results = False
        self.scanning = True
        self.connection.configure(text="Rilevamento dei dischi e delle unità protette…", fg=MUTED)
        self._controls()

        def work():
            try:
                inventory = self.backend.scan()
            except Exception as error:
                inventory = Inventory((), False, str(error), simulated=self.demo)
            self.events.put({"type": "inventory", "inventory": inventory})
        Thread(target=work, name="dejavu-inventory", daemon=True).start()

    def _automatic_scan(self):
        if not self.selected():
            self.scan()
        if not self.closing:
            self.root.after(15000, self._automatic_scan)

    def show_inventory(self, inventory):
        previous = {row.disk.key for row in self.rows.values() if row.selected.get()}
        for row in self.rows.values():
            row.frame.destroy()
        self.rows.clear()
        self.inventory = inventory
        self.scanning = False
        for disk in inventory.disks:
            row = DiskRow(self.list_frame, disk, self.selection_changed, inventory.protection_ok)
            row.selected.set(disk.key in previous and not disk.protected)
            self.rows[disk.number] = row
        if inventory.protection_ok:
            protected = sum(disk.protected for disk in inventory.disks)
            self.connection.configure(text=f"{len(inventory.disks)} dischi rilevati · {protected} protetti · "
                                      "USB e SATA rilevati automaticamente. Controlla modello e numero di serie.", fg=MUTED)
        else:
            self.connection.configure(text="Cancellazione bloccata: " + (inventory.error or "protezione del sistema non confermata"), fg=RED)
        self.selection_changed()

    def confirm(self, disks):
        answer = {"yes": False}
        window = tk.Toplevel(self.root)
        window.title("Conferma i dischi da cancellare")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(760, max(420, screen_width - 80))
        height = min(560, max(360, screen_height - 140))
        x = max(0, min(self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2,
                       screen_width - width))
        y = max(0, min(self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2,
                       screen_height - height))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(min(width, 620), min(height, 420))
        window.configure(bg="white")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        # Only the list receives spare space or shrinks. The action row keeps
        # its requested height, even with large fonts / Windows display scaling.
        window.rowconfigure(2, weight=1)
        heading = tk.Label(window, text="I dati dei dischi elencati verranno cancellati.",
                           bg="white", fg=RED, font=(FONT, 14, "bold"),
                           anchor="w", justify="left", wraplength=width - 44)
        heading.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 12))
        instruction_text = "Controlla il numero di serie sull'etichetta di ogni disco."
        if not self.demo:
            instruction_text += "\nChiudi Esplora file e i programmi che usano i dischi da cancellare."
        instruction = tk.Label(window, text=instruction_text,
                               bg="white", fg=INK, font=(FONT, 11),
                               anchor="w", justify="left", wraplength=width - 44)
        instruction.grid(row=1, column=0, sticky="ew", padx=22)
        area = tk.Frame(window, bg="white", padx=22, pady=15)
        area.grid(row=2, column=0, sticky="nsew")
        text = tk.Text(area, font=(FONT, 11), wrap="word", bg=BG, fg=INK,
                       relief="flat", padx=12, pady=10, width=1, height=1)
        bar = ttk.Scrollbar(area, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        for disk in disks:
            kind = {"HDD": "Disco meccanico", "SSD": "SSD", "UNKNOWN": "Tipo da verificare"}[disk.kind]
            text.insert("end", f"Disco {disk.number} · {disk.model}\nNumero di serie: {disk.serial or 'NON DISPONIBILE'}\n"
                        f"{human_size(disk.size)} · {kind} · {disk.bus}\n")
            if disk.kind == "SSD":
                text.insert("end", "Procedura nativa SSD: una volta iniziata deve terminare sul dispositivo.\n")
            elif disk.kind != "HDD":
                text.insert("end", "Questa unità sarà segnalata come non cancellata in questa versione.\n")
            text.insert("end", "\n")
        text.configure(state="disabled")
        buttons = tk.Frame(window, bg="white", padx=22, pady=18)
        buttons.grid(row=3, column=0, sticky="ew")
        def accept():
            answer["yes"] = True
            window.destroy()
        def dismiss(event=None):
            window.destroy()
            return "break"
        ttk.Button(buttons, text="Confermo, avvia", style="Primary.TButton", command=accept).pack(side="right")
        cancel_button = ttk.Button(buttons, text="Annulla", command=dismiss)
        cancel_button.pack(side="right", padx=(0, 12))
        def reflow(event):
            if event.widget is window:
                wrap = max(200, event.width - 44)
                heading.configure(wraplength=wrap)
                instruction.configure(wraplength=wrap)
        window.bind("<Configure>", reflow)
        window.bind("<Escape>", dismiss)
        window.protocol("WM_DELETE_WINDOW", dismiss)
        window.grab_set()
        cancel_button.focus_set()
        self.root.wait_window(window)
        return answer["yes"]

    def start(self):
        if self.busy or self.scanning or self.have_results or not self.inventory.protection_ok:
            return
        disks = self.selected()
        if not disks:
            return
        self.confirming = True
        self._controls()
        try:
            confirmed = self.confirm(disks)
        finally:
            self.confirming = False
        if not confirmed:
            self._controls()
            return
        self.busy = True
        self.have_results = False
        self.reports = None
        self.cancel.clear()
        self.summary.configure(text="Cancellazione in corso…", fg=TEAL)
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.connection.configure(text="Lascia collegati e alimentati i dischi fino al termine della verifica.", fg=TEAL)
        for disk in disks:
            row = self.rows[disk.number]
            row.progress["value"] = 0
            row.phase("In attesa")
            row.detail.configure(text="")
        self._controls()
        Thread(target=run_batch, args=(disks, self.inventory, self.backend, self.cancel,
                                      self.events.put, self.report_folder, self.concurrency),
               name="dejavu-batch", daemon=False).start()

    def stop(self):
        if self.busy and messagebox.askyesno("Interrompere il lavoro?",
                "Le operazioni incomplete saranno indicate come INTERROTTE.\n"
                "Le cancellazioni native SSD già avviate vengono seguite fino al termine.\n"
                "I nuovi lavori non inizieranno. I dischi incompleti possono contenere dati.\n\nInterrompere?", parent=self.root):
            self.cancel.set()
            self.stop_button.configure(state="disabled")
            self.summary.configure(text="Interruzione in corso…", fg=AMBER)

    def _events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event["type"]
                if kind == "inventory":
                    self.show_inventory(event["inventory"])
                elif kind in ("phase", "progress", "result"):
                    row = self.rows.get(event["number"])
                    if row:
                        if kind == "phase":
                            row.phase(event["phase"])
                        elif kind == "progress":
                            row.update_progress(event)
                        else:
                            row.finish(event["result"])
                elif kind == "batch_done":
                    self.batch_done(event)
        except Empty:
            pass
        if not self.closing:
            self.root.after(80, self._events)

    def batch_done(self, event):
        self.busy = False
        self.have_results = True
        self.reports = event["reports"]
        self.stop_button.configure(state="disabled")
        self.open_button.configure(state="normal" if self.reports else "disabled")
        counts = Counter(result.status for result in event["results"])
        text = (f"{counts['SUCCESS']} completati · {counts['FAILED']} non confermati\n"
                f"{counts['BLOCKED']} non cancellati · {counts['CANCELLED']} interrotti")
        all_clean = all(result.status == "SUCCESS" and not result.warnings for result in event["results"])
        self.summary.configure(text=text, fg=GREEN if all_clean else AMBER)
        self.connection.configure(text=event["report_error"] or "Lavoro terminato. Apri il rapporto per i dettagli; ‘Rileva dischi’ prepara il prossimo gruppo.",
                                  fg=RED if event["report_error"] else MUTED)
        # Every subsequent batch requires a fresh scan and a new selection.
        for row in self.rows.values():
            row.selected.set(False)
        self._controls()
        if event["report_error"]:
            messagebox.showerror("Problema nei rapporti", event["report_error"], parent=self.root)

    def open_report(self):
        if self.reports:
            path = self.reports[0].resolve()
            if os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(path.as_uri())

    def close(self):
        if self.busy:
            self.stop()
            return
        self.closing = True
        self.root.destroy()
        if self.demo:
            self.backend.cleanup()
