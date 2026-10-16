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
    <ul>{items}</ul><p>{escape(data['notice'])}</p></section>
    <section class="completion"><h2>Completamento e validazione del responsabile</h2>
    <p>Da completare sulla copia cartacea o PDF finale, dopo la verifica dell'incarico e degli esiti.
    Questi campi non sono compilati o sottoscritti automaticamente dal programma.</p>
    <p>Affidante / provenienza del lotto: ____________________________________________________<br>
    Riferimento incarico e autorizzazione alla cancellazione: __________________________________<br>
    Operatore (nome e cognome) / postazione: ______________________________________________<br>
    Firma dell'operatore / data: _________________________________________________________</p>
    <p>Validazione per la destinazione prevista: &#9633; accettata &#9633; respinta &#9633; da approfondire<br>
    Destinazione, riserve o interventi richiesti: ______________________________________________<br>
    Responsabile della validazione (nome, ruolo) / firma / data: _________________________________</p>
    <p class="muted">Validazione umana nel registro elettronico: non acquisita. Nessuna firma elettronica
    qualificata o marca temporale qualificata è apposta dal programma. Un eventuale documento finale
    firmato va conservato insieme al JSON originale e collegato all'identificativo di questo rapporto.</p></section>'''
