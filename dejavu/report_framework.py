"""Documentary context, never an automatic legal or Purge certification."""
from copy import deepcopy
from html import escape

REFERENCES = (
    {
        "id": "GDPR", "category": "Quadro normativo europeo",
        "title": "Regolamento (UE) 2016/679 — artt. 5, par. 2, 24 e 32",
        "url": "https://www.garanteprivacy.it/regolamentoue",
        "purpose": "Responsabilizzazione, documentazione delle misure e sicurezza adeguata al rischio. Il GDPR non prescrive un unico algoritmo di cancellazione.",
    },
    {
        "id": "GPDP-2008-1571514", "category": "Riferimento italiano di settore",
        "title": "Garante per la protezione dei dati personali — provvedimento 13 ottobre 2008, doc. web 1571514",
        "url": "https://www.garanteprivacy.it/web/guest/home/docweb/-/docweb-display/docweb/1571514",
        "purpose": "Protezione dei dati nella dismissione e nel reimpiego e documentazione delle operazioni svolte. Riferimento antecedente al GDPR, da leggere nel quadro vigente e dell'evoluzione tecnologica: non si attesta l'applicazione letterale delle tecniche descritte nel 2008.",
    },
    {
        "id": "NIST-SP-800-88R2", "category": "Riferimento tecnico, non normativa italiana o UE",
        "title": "NIST SP 800-88 Rev. 2, settembre 2025 — sezioni 4.5, 4.6 e appendice C",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-88r2.pdf",
        "purpose": "Distinzione tra verifica dell'operazione e validazione per la destinazione prevista; tracciabilità del supporto e documentazione degli esiti. Il richiamo non attesta una certificazione NIST o la conformità integrale della procedura.",
    },
)

DOCUMENT_NOTICE = (
    "Questo rapporto documenta gli esiti registrati dal programma sul supporto identificato. "
    "I riferimenti richiamati descrivono il contesto e i criteri documentali; non sono attestazioni "
    "automatiche di conformità GDPR, certificazioni del software o garanzie Purge. "
    "La valutazione di adeguatezza al rischio e l'accettazione per il riuso richiedono una "
    "validazione organizzativa separata. Errori, blocchi e interruzioni non attestano una cancellazione riuscita."
)


def documentation(document_id):
    return {
        "document_id": document_id,
        "document_type": "Rapporto tecnico delle operazioni di cancellazione",
        "organization": "Credere per Vedere OdV — Progetto Dejavu",
        "framework_review_date": "2026-10-16",
        "references": deepcopy(REFERENCES),
        "notice": DOCUMENT_NOTICE,
        "operator": None, "assignor": None, "assignment_reference": None,
        "human_validation": {"status": "NOT_RECORDED", "reviewer": None, "decision": None},
        "qualified_signature": "NOT_APPLIED",
        "qualified_timestamp": "NOT_APPLIED",
        "time_source": "Orologio locale del PC; data e ora non costituiscono una marca temporale qualificata",
        "purge_certified": False, "gdpr_certified": False,
    }


def documentation_html(data):
    items = "".join(
        f'<li><strong>{escape(item["category"])}</strong> — '
        f'<a href="{escape(item["url"], quote=True)}">{escape(item["title"])}</a>. '
        f'{escape(item["purpose"])}</li>' for item in data["references"])
    return f'''<section class="framework"><h2>Riferimenti di contesto e limiti dell'attestazione</h2>
    <ul>{items}</ul><p>{escape(data['notice'])}</p></section>'''


def completion_html(data, *, simulated=False):
    """Large-print, handwriting-friendly sheets linked to the same report."""
    identifier = escape(data["document_id"])
    simulation = '<p class="form-simulation">SIMULAZIONE - solo file di prova</p>' if simulated else ""

    def header(title, sheet):
        return f'''<p class="form-organization">CREDERE PER VEDERE OdV - PROGETTO DEJAVU</p>
        <h2>{title}</h2><p class="form-id">Rapporto: <strong>{identifier}</strong><br>
        Scheda di compilazione {sheet} di 2</p>{simulation}'''

    def field(label, lines=1):
        writing = '<span class="handwriting-line"></span>' * lines
        return f'''<div class="write-field"><p class="write-label">{escape(label)}</p>
        <div class="handwriting-area" aria-hidden="true">{writing}</div></div>'''

    return f'''<section class="completion" aria-label="Scheda di compilazione dell'operatore">
    {header("Compilazione dell'operatore", 1)}
    <p class="form-note">Compilare a mano dopo aver verificato l'incarico e gli esiti del rapporto.</p>
    {field("Affidante / provenienza del lotto", 2)}
    {field("Incarico e autorizzazione alla cancellazione", 2)}
    {field("Operatore (nome e cognome)")}
    {field("Postazione utilizzata")}
    <div class="signature-fields">{field("Firma dell'operatore")}{field("Data")}</div>
    <p class="form-note form-footer">Campi da compilare sulla copia cartacea o PDF finale.
    Il programma non compila i nomi e non appone firme.</p></section>
    <section class="completion" aria-label="Scheda di validazione del responsabile">
    {header("Validazione del responsabile", 2)}
    <p class="form-note">Da completare dopo la verifica degli esiti e della destinazione prevista.</p>
    <div class="write-field"><p class="write-label">Validazione per la destinazione prevista</p>
    <div class="decision-options"><span class="decision-choice"><span class="decision-box" aria-hidden="true"></span>Accettata</span>
    <span class="decision-choice"><span class="decision-box" aria-hidden="true"></span>Respinta</span>
    <span class="decision-choice"><span class="decision-box" aria-hidden="true"></span>Da approfondire</span></div></div>
    {field("Destinazione, riserve e interventi richiesti", 3)}
    {field("Responsabile (nome, cognome e ruolo)", 2)}
    <div class="signature-fields">{field("Firma del responsabile")}{field("Data")}</div>
    <p class="form-note form-footer">Validazione umana nel registro elettronico: non acquisita.
    Nessuna firma elettronica qualificata o marca temporale qualificata è apposta dal programma.
    Conservare la copia finale firmata insieme al rapporto completo e al JSON originale,
    collegati all'identificativo riportato sopra.</p></section>'''
