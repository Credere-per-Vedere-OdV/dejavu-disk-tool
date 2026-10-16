"""Offline HTML + JSON reports, with explicit coverage and failure outcomes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
import hashlib
import json
import os
import re
import uuid

from . import __version__
from .core import Inventory, JobResult, human_size, human_duration
from .report_framework import documentation, documentation_html


LABELS = {"SUCCESS": "CANCELLATO E VERIFICATO", "FAILED": "NON CONFERMATO",
          "BLOCKED": "NON CANCELLATO", "CANCELLED": "INTERROTTO"}


def atomic_text(path: Path, text: str):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def save_disk_record(folder: Path, result: JobResult, batch_id: str) -> Path:
    """Persist each concluded job before waiting for the rest of the batch.

    A record describes the recorded outcome, including failures or blocks;
    its existence alone never means that erasure succeeded.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", batch_id):
        raise ValueError("Identificativo del lotto non valido.")
    destination = folder / "esiti_dischi" / batch_id
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"Disco-{result.disk.number:03d}.json"
    payload = {"application": "Dejavu DiskTool", "version": __version__,
               "record_kind": "Esito di una singola unità",
               "batch_id": batch_id, "simulated": result.disk.simulated,
               "documentation": documentation(f"{batch_id}-Disco-{result.disk.number:03d}"),
               "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "result": result.to_dict()}
    atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def save_reports(folder: Path, inventory: Inventory, results: list[JobResult],
                 concurrency: int, *, batch_id: str | None = None) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    identifier = batch_id or (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", identifier):
        raise ValueError("Identificativo del rapporto non valido.")
    prefix = "SIMULAZIONE-" if inventory.simulated else ""
    base = prefix + "Dejavu-" + identifier
    json_path, html_path = folder / (base + ".json"), folder / (base + ".html")
    payload = {"application": "Dejavu DiskTool", "version": __version__,
               "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "simulated": inventory.simulated, "concurrency": concurrency,
               "batch_id": identifier, "documentation": documentation(identifier),
               "policy": "Procedura automatica: HDD Clear con zeri e rilettura integrale; SSD SATA con ATA Sanitize Block Erase o ATA Enhanced Security Erase",
               "coverage": "HDD: spazio indirizzabile esposto al computer. SSD: operazione interna al controller ed esito nativo; nessun conteggio di byte riletti. Non è una certificazione Purge né una diagnosi completa del disco.",
               "protected_disks": [{"number": disk.number, "model": disk.model,
                                    "reasons": list(disk.protected_reasons)}
                                   for disk in inventory.disks if disk.protected],
               "results": [result.to_dict() for result in sorted(results, key=lambda result: result.disk.number)]}
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_text(json_path, json_text)
    json_digest = hashlib.sha256(json_text.encode("utf-8")).hexdigest()
    rows = []
    for result in sorted(results, key=lambda item: item.disk.number):
        warnings = "".join("<li>" + escape(warning) + "</li>" for warning in result.warnings)
        outcome = LABELS[result.status]
        if result.disk.kind == "SSD" and result.status == "SUCCESS":
            outcome = "SSD SANITIZZATO — ESITO DEL DISPOSITIVO CONFERMATO"
        css_status = result.status.lower()
        if result.status == "SUCCESS" and result.warnings:
            outcome += " — CON AVVISI"
            css_status = "success_warning"
        if result.disk.kind == "SSD":
            completion = {"not_started": "Non avviata", "unconfirmed": "Non confermata",
                          "device_confirmed": "Confermata dal dispositivo"}.get(
                              result.native_details.get("completion"), "Non confermata")
            controls = "Verifica nativa: " + escape(completion) + "<br>Conteggi di scrittura/rilettura dal PC: non applicabili"
        else:
            controls = (f"Scritti: {result.written:,} / {result.disk.size:,} byte<br>"
                        f"Verificati: {result.verified:,} / {result.disk.size:,} byte")
        rows.append(f'''<tr><td><strong>Disco {result.disk.number} · {escape(result.disk.model)}</strong><br>
            Seriale: {escape(result.disk.serial)}<br>{escape(human_size(result.disk.size))} · {escape(result.disk.bus)}<br>
            Firmware: {escape(result.disk.firmware_revision or 'Non disponibile')}</td>
            <td class="{css_status}"><strong>{escape(outcome)}</strong><br>{escape(result.message)}
            {('<ul>' + warnings + '</ul>') if warnings else ''}</td>
            <td>{escape(result.method)}<br>{controls}<br>
            Inizio attività: {escape(result.started_at or 'Non registrato')}<br>
            Fine attività: {escape(result.finished_at or 'Non registrata')}<br>
            Durata: {escape(human_duration(result.duration_seconds))}</td></tr>''')
    counts = Counter(result.status for result in results)
    simulation = "<p class='demo'><strong>SIMULAZIONE:</strong> gli esiti riguardano soltanto file di prova.</p>" if inventory.simulated else ""
    protected = "".join(f"<li>{escape(disk.model)} — {escape('; '.join(disk.protected_reasons))}</li>"
                        for disk in inventory.disks if disk.protected)
    framework = documentation_html(payload["documentation"])
    html = f'''<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Rapporto Dejavu {escape(identifier)}</title><style>
    body{{font:16px system-ui,sans-serif;color:#17253b;background:#f2f5f9;margin:0;padding:32px}}
    main{{max-width:1120px;margin:auto;background:white;padding:32px;border-radius:16px}}
    h1{{font-size:30px;margin:8px 0 12px}} .muted{{color:#4e5e73}} table{{border-collapse:collapse;width:100%;margin:24px 0}}
    th,td{{text-align:left;vertical-align:top;padding:16px;border:1px solid #d7e0eb;line-height:1.6;overflow-wrap:anywhere}}
    th{{background:#eaf0f8}} .success{{background:#e6f6ec;color:#175733}} .failed,.cancelled{{background:#fff0ed;color:#86291c}}
    .blocked,.success_warning{{background:#fff6df;color:#684507}} .demo{{background:#e8e3ff;padding:16px;border-radius:8px}}
    .summary{{font-size:18px;line-height:1.7}} .framework,.completion{{font-size:13px;line-height:1.5}}
    .framework li{{margin:6px 0}} .completion{{border-top:1px solid #d7e0eb;margin-top:20px}}
    .integrity{{font-size:12px;overflow-wrap:anywhere}} .completion p{{line-height:1.8}}
    @media print{{body{{padding:0;background:white;font-size:12px}}main{{padding:6px}}h1{{font-size:23px}}
    h2{{font-size:15px}}th,td{{padding:8px;line-height:1.4}}thead{{display:table-header-group}}
    tr,.completion{{break-inside:avoid}}.framework,.completion{{font-size:11px}}}}
    </style><main><p class="muted">CREDERE PER VEDERE OdV · PROGETTO DEJAVU</p>
    <h1>Rapporto tecnico di cancellazione</h1><p>Identificativo: <strong>{escape(identifier)}</strong><br>
    {escape(payload['created_at'])} · Versione {escape(__version__)}<br>
    <span class="muted">Data e ora dell'orologio locale del PC; nessuna marca temporale qualificata.</span></p>
    {simulation}<p class="summary"><strong>{counts['SUCCESS']}</strong> completati · <strong>{counts['FAILED']}</strong> non confermati ·
    <strong>{counts['BLOCKED']}</strong> non cancellati · <strong>{counts['CANCELLED']}</strong> interrotti</p>
    <table><thead><tr><th>Disco</th><th>Esito</th><th>Controlli eseguiti</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    <h2>Procedura e copertura</h2><p>{escape(payload['policy'])}</p><p>{escape(payload['coverage'])}</p>
    <h2>Unità protette</h2><ul>{protected}</ul>
    {framework}
    <p class="integrity">Registro elettronico originale: <a href="{escape(json_path.name, quote=True)}">{escape(json_path.name)}</a><br>
    SHA-256 del JSON: {escape(json_digest)}<br>Questa impronta consente il confronto del file; da sola non prova
    l'identità dell'autore, la data o l'immutabilità del documento. Non è una firma digitale qualificata.</p>
    <p class="muted">Le unità con esito non confermato, non cancellato o interrotto richiedono un nuovo intervento prima della donazione.
    Un esito di cancellazione riuscita non attesta l'affidabilità futura dell'hardware.</p></main></html>'''
    atomic_text(html_path, html)
    return html_path, json_path
