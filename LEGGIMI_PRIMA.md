# Dejavu DiskTool — beta Windows

Versione 0.5.2-beta · 16 ottobre 2026

Per Credere per Vedere OdV e il Progetto Dejavu — Laboratorio di Riciclo e Terapia Occupazionale. Una sola procedura: collegare i dischi, selezionare quelli da cancellare, confermare e leggere l'esito di ciascuno. Non occorre indicare quante docking sono collegate. Il progetto deriva dall'analisi del DFTool di Alessio, con un motore Windows separato.

La 0.5.0 migliora la resa dei loghi originali con ridimensionamento Lanczos e immagini adattate alla densità del display. Aggiunge un avviatore separato per aggiornamenti firmati da GitHub Releases, conservando il motore HDD/SSD e le protezioni della 0.4.1. Vedere `AGGIORNAMENTI_GITHUB.md` per la prima configurazione e la compilazione centrale.

La **0.5.1** integra nei rapporti HTML e nei JSON i riferimenti di contesto GDPR/Garante e quelli documentali NIST SP 800-88 Rev. 2. Aggiunge identificativi collegati tra lotto e registri per unità, impronta SHA-256 del JSON sulla stampa e campi manuali per affidante, incarico, operatore, firma e validazione del responsabile. Il software non appone firme qualificate e non certifica automaticamente conformità normativa o livello Purge. Vedere `RAPPORTI_E_RIFERIMENTI.md`.

La **0.5.2** rende più leggibile la parte da compilare a mano: due schede A4 dedicate, etichette da 18 punti, spazi a tutta larghezza e righe da 12 mm. Ogni scheda riporta l'identificativo del rapporto e le simulazioni sono indicate anche sulle schede. La compilazione resta manuale e separata dai dati JSON. È inclusa la correzione del test ZIP per Windows. Per ricreare l'EXE seguire `AGGIORNA_ALLA_0.5.2.txt`.

La 0.4.1 aggiunge **Seleziona lotto**, che seleziona con un clic le unità ammesse dai controlli preliminari, e un registro JSON salvato appena termina il lavoro su ogni disco. Rimangono una conferma iniziale per il lotto e i controlli nativi prima di ciascuna cancellazione. Nessun nuovo disco viene cancellato automaticamente quando viene collegato. Le unità non protette che non superano i controlli sono indicate come “Escluso dal lotto”, con la motivazione; i registri e il riepilogo riguardano le unità effettivamente selezionate.

**Stato:** sorgenti, GUI italiana, simulazione, test e script per creare l'EXE su Windows. I test usano file temporanei e API simulate. I comandi SSD, la docking, i driver Windows e l'EXE richiedono ancora un collaudo su hardware reale. Questa beta non costituisce una certificazione Purge per banche o altri donatori.

## Aggiornamento e prima prova

1. Lasciare terminare eventuali lavori della versione precedente, quindi chiuderla.
2. Estrarre tutto il nuovo ZIP in una cartella nuova sul disco di sistema.
3. Con Python già installato, aprire `Prova_interfaccia.cmd`. Modifica soltanto piccoli file di esempio, senza aprire dischi fisici.
4. Selezionare i quattro esempi non protetti e avviare. Esiti attesi: due HDD riusciti, uno SSD riuscito, un HDD con errore di lettura. Il rapporto è marcato SIMULAZIONE.
5. Per il primo collaudo reale, collegare **un solo SSD di prova, privo di dati da conservare**, e aprire `Rilevamento_senza_cancellazione.cmd`. Controllare seriale, modello, firmware e metodi prima di cancellarlo.

Per i sorgenti serve Python 3.12, 3.13, 3.14 o 3.15 a 64 bit, con Tcl/Tk e launcher. Gli script CMD preparano automaticamente un ambiente dedicato con Pillow e cryptography; al primo avvio dei sorgenti serve Internet. Per avviare direttamente da terminale installare prima `requirements.txt`. Le dipendenze sono incorporate nella versione EXE e non richiedono installazioni sui PC degli operatori. `GUIDA_MAURO_RINNA.html` descrive il lavoro degli operatori. I rapporti inclusi in `esempi_rapporti` sono esempi, non riguardano i dischi collegati al PC.

## Procedura automatica

| Tipo di disco | Comportamento |
| --- | --- |
| HDD identificato | Sovrascrittura con zeri di tutta la capacità esposta al PC, flush e rilettura con confronto integrale. |
| SSD SATA con Sanitize Block Erase | Comando ATA Sanitize Block Erase, controllo dello stato prima dell'avvio e monitoraggio fino alla conferma del dispositivo. |
| SSD SATA senza Block Erase, con Enhanced Security Erase | ATA Enhanced Security Erase se la sicurezza ATA è disponibile; password temporanea protetta sul PC prima di inviarla al disco. |
| SSD con metodo, sicurezza o collegamento non disponibili | Non cancellato; affidarlo al responsabile tecnico. Nessun ripiego sulla sovrascrittura HDD. |
| NVMe, identità incerta, RAID o unità aggregate | Nessuna cancellazione in questa versione. |
| Windows e altre unità protette | Visibili ma non selezionabili. |

Non c'è un algoritmo da scegliere. Essere un SSD SATA non garantisce che esponga uno dei metodi implementati. La compatibilità dipende dal firmware e dal passaggio dei comandi attraverso Windows, driver e collegamento. Sanitize può essere bloccato da Windows anche su un disco secondario; una docking può consentire IDENTIFY e rifiutare la cancellazione. Se lo stato Sanitize non è leggibile, il programma si ferma senza passare automaticamente a un altro metodo. Anche SATA diretto richiede il collaudo. Non è incluso un ambiente avviabile WinPE o Linux.

**Copertura e verifica:** sugli HDD il successo riguarda lo spazio indirizzabile esposto al computer, senza attestare settori riallocati o aree HPA/DCO nascoste. Sugli SSD l'operazione è interna al firmware: si verificano identità ed esito nativo, senza rileggere tutta la memoria NAND o inventare conteggi di byte sovrascritti. Il successo del firmware non dimostra da solo l'irrecuperabilità in laboratorio. Per dichiarare Purge occorrono validazione per modello/firmware e requisiti concordati con il donatore.

## Rilevamento, protezioni e avvio reale

`Avvia_programma.cmd` richiede i permessi di amministratore. Nessun disco viene selezionato o cancellato automaticamente. Prima di confermare controllare il seriale sull'etichetta e chiudere Esplora file e le applicazioni che usano i dischi scelti.

Sono protette le unità di Windows in esecuzione, di avvio/sistema EFI, di paging, del programma, dell'interprete e dei rapporti, anche con volumi montati dentro cartelle. Se le protezioni non sono ricostruibili, tutte le operazioni sono bloccate. Seriale mancante o duplicato impedisce di procedere. Identità, numero fisico, capacità, settori e firmware vengono ricontrollati sul dispositivo aperto.

Per USB occorrono modello e seriale firmware ATA associabili con certezza al disco Windows; il solo seriale della docking non basta. L'accesso esclusivo ai volumi viene ritentato in caso di errori temporanei, senza smontare volumi non bloccabili o chiudere forzatamente altri programmi. La finestra di conferma conserva i pulsanti in una riga separata dall'elenco scorrevole.

`Rilevamento_senza_cancellazione.cmd` salva la diagnostica in `%LOCALAPPDATA%\CrederePerVedere\DejavuDiskTool\diagnostica_windows.json`: metodi SSD, stato di sicurezza, firmware, identità e informazioni del controller quando disponibili. Interroga metadati e ATA IDENTIFY; non smonta volumi, non cambia lo stato dei dischi e non scrive sui loro settori.

## Progressione, interruzione ed esiti

Per gli HDD la barra comprende scrittura e rilettura: a metà manca la verifica. Per Sanitize si mostra la percentuale del dispositivo. Con Enhanced Security Erase la barra animata indica un comando in corso e non misura byte cancellati.

**Una cancellazione SSD già avviata non si arresta con “Interrompi”.** Il programma continua a seguirla fino al termine, interrompe gli HDD e impedisce di avviare i lavori in coda. Lasciare alimentazione e collegamenti stabili. Il programma chiede a Windows di evitare la sospensione automatica, ma non può impedire uno spegnimento manuale o una perdita di corrente.

- **HDD cancellato e verificato:** scrittura e rilettura complete.
- **SSD sanitizzato, esito confermato:** completamento nativo e identità confermati; non equivale a certificazione Purge.
- **Con avvisi:** leggere il rapporto e coinvolgere il responsabile tecnico.
- **Non confermato / Interrotto:** operazione incompleta; non donare il disco come cancellato.
- **Non cancellato:** i controlli non hanno consentito di iniziare.

I rapporti HTML/JSON si trovano in `%LOCALAPPDATA%\CrederePerVedere\DejavuDiskTool\rapporti`. Le simulazioni usano `rapporti_demo` e sono marcate come tali. Modello, seriale, metodo, durata, esito, errori e avvisi restano localmente sul PC. I conteggi HDD e la conferma nativa SSD sono distinti: i conteggi host SSD nel JSON sono `null`. Il motore non invia dati dei dischi o rapporti a servizi esterni. L'avviatore della versione EXE richiede a GitHub esclusivamente metadati di release e pacchetti del programma; seriali, diagnostiche e registri non vengono caricati.

In `rapporti\esiti_dischi\<identificativo del lotto>` la 0.4.1 salva un JSON per ogni lavoro concluso, anche quando l'esito è bloccato, fallito o interrotto. L'esistenza del file non significa che la cancellazione sia riuscita: occorre leggerne l'esito. Questi registri vengono salvati prima di attendere gli altri dischi; il rapporto HTML/JSON riepilogativo resta generato al termine del lotto. I problemi di salvataggio sono segnalati senza cambiare l'esito della cancellazione.

Un arresto forzato può impedire il rapporto: un processo iniziato non dimostra una cancellazione riuscita. La procedura non crea un volume NTFS e non attesta la salute futura dell'hardware. Se Windows propone di inizializzare il disco, attendere chi si occupa del ricondizionamento.

## Postazione per lotti autonomi

Il flusso previsto è: caricare tutti i dischi, rilevarli, premere **Seleziona lotto**, controllare l'elenco e confermare una volta. La coda prosegue automaticamente, senza conferme per ogni unità. Il limite iniziale resta 2 lavori contemporanei; si può impostare fino a 8 in `impostazioni.ini`. Gli errori di una unità non vengono considerati successi e non impediscono di elaborare le altre unità quando i loro collegamenti restano utilizzabili.

Per il laboratorio partire con quattro posti disponibili: due docking doppie, oppure SATA diretto e la docking già presente. Le docking devono esporre dischi separati e lavorare come collegamento al PC. La loro funzione di clone non effettua la procedura di cancellazione del programma.

Prima di lasciare lavorare la postazione durante la notte, completare una prova assistita sulla configurazione definitiva, soprattutto sugli SSD. Alimentazione e ventilazione devono essere adeguate; Windows non deve riavviarsi durante il lotto e i dischi devono restare collegati. Il programma richiede di evitare la sospensione automatica, ma non impedisce uno spegnimento manuale o un riavvio di sistema.

Il numero di dischi caricati determina quanto lavoro può essere svolto senza sostituzioni manuali; quanti finiranno entro il mattino dipende anche da capacità, velocità e collegamenti. Misurare un primo lotto prima di espandere la postazione. Il programma **non riprende automaticamente dopo un riavvio**: le unità senza un esito completo restano da verificare e, quando necessario, da cancellare nuovamente.

## Password temporanea SSD e recupero tecnico

Enhanced Security Erase richiede una password ATA temporanea casuale. Windows DPAPI la protegge e un registro viene salvato in `%LOCALAPPDATA%\CrederePerVedere\DejavuDiskTool\recupero_ssd` **prima** di impostarla sul disco. Non viene scritta in chiaro nei rapporti. Dopo il completamento confermato il registro viene eliminato; dopo un errore l'SSD potrebbe restare protetto dalla password.

In quel caso conservare registro, PC e profilo Windows elevato usato nell'operazione; la chiave DPAPI è legata al profilo e normalmente al computer. Il rapporto indica il percorso da conservare. Non reinstallare Windows o cancellare il profilo prima dell'assistenza tecnica. Il recupero è compito del responsabile tecnico.

Dopo aver verificato che l'operazione precedente sia terminata e il programma che l'ha avviata sia chiuso, il tecnico può rimuovere la password creata dal programma. Il recupero controlla seriale, firmware, registro e processo precedente; non invia un comando di cancellazione e non attesta la sanitizzazione. Ripetere poi la cancellazione.

Esempio, sostituendo percorso, numero fisico attuale e seriale esatto dopo un nuovo rilevamento:

```console
DejavuDiskTool.exe --recupera-ssd "C:\percorso\SSD-registro.json" --disco 2 --conferma "SERIALE_ESATTO"
```

Con i sorgenti sostituire l'EXE con `python main.py`. Questo recupero non è un comando per password sconosciute impostate da altri strumenti.

## Più dischi e creazione EXE

Il limite iniziale è 2 dischi contemporaneamente; gli altri attendono. Chi prepara il PC può impostare `dischi_contemporanei` da 1 a 8 in `impostazioni.ini`. Le docking devono esporre unità separate, senza modalità RAID o clone autonoma. Hub e docking condividono la banda USB. Collegare SATA interni a PC spento, salvo un banco predisposto per l'inserimento a caldo.

Sul PC Windows del responsabile, con Python a 64 bit, aprire `Crea_EXE.cmd`: prepara le dipendenze, esegue i test e costruisce applicazione, avviatore e pacchetti firmati. Alla prima compilazione crea la chiave privata nel profilo del responsabile, fuori dalla cartella dei sorgenti: conservarne un backup riservato e usare sempre la stessa per gli aggiornamenti.

Il programma per i colleghi è **`release\DejavuDiskTool\AvviaDejavu.exe`**. Distribuire una volta `release\DejavuDiskTool-Installazione-Windows-x64.zip`, estrarre tutta la cartella sul disco di Windows in un percorso scrivibile e creare un collegamento a quell'avviatore. Non separare `_internal`, `versioni` e `attiva.json`. Chi usa la versione compilata non deve installare Python. Questo ZIP contiene sorgenti e script di compilazione, non un EXE già costruito e collaudato.

Il controllo avviene prima dell'apertura e dell'elevazione: firma Ed25519, SHA-256 e verifica della struttura ZIP, preparazione in una cartella nuova, attivazione atomica. Senza rete o dopo un aggiornamento rifiutato resta utilizzabile la versione installata. Durante la cancellazione non avvengono aggiornamenti. Rapporti e impostazioni della postazione vengono conservati. L'avviatore si aggiorna manualmente se necessario; gli aggiornamenti automatici riguardano il programma e le sue librerie.

La destinazione proposta è `Credere-per-Vedere-OdV/dejavu-disk-tool`: repository e prima release devono ancora essere configurati dal responsabile. Le versioni precedenti richiedono questa prima sostituzione manuale. La guida **`AGGIORNAMENTI_GITHUB.md`** contiene i passaggi e i quattro allegati da pubblicare per ogni release.

## Riferimenti e sviluppo

```console
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python prova_motore.py
python main.py --demo
```

- [NIST SP 800-88 Rev. 2](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-88r2.pdf): principi e validazione della sanitizzazione.
- [Seagate — Sanitizing Storage Devices](https://github.com/Seagate/openSeaChest/wiki/Sanitizing-Storage-Devices) e [Sanitize Feature](https://github.com/Seagate/openSeaChest/wiki/Sanitize-Feature): metodi nativi, limiti Windows e collegamenti.
- [Microsoft ATA pass-through](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ni-ntddscsi-ioctl_ata_pass_through) e [SCSI pass-through direct](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ni-ntddscsi-ioctl_scsi_pass_through_direct): trasporto dei comandi.
- [Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata): protezione del registro password.
- [PyInstaller](https://pyinstaller.org/en/stable/): la compilazione Windows va eseguita su Windows.

I riferimenti descrivono i protocolli e non certificano questo programma. `dejavu/ssd.py` contiene i comandi nativi separati dal motore HDD e dalle interrogazioni IDENTIFY. Le risorse originali sono in `assets`.
