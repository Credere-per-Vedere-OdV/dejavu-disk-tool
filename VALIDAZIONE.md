# Validazione della beta 0.5.2

16 ottobre 2026 — Linux, Python 3.12 a 64 bit. Nessun Windows nativo disponibile e nessun disco reale aperto.

## Eseguito

- Compilazione sintattica dei sorgenti.
- 120 test unittest superati: 88 test per il motore e i registri, 27 per gli aggiornamenti firmati e 5 per la tracciabilità e i limiti documentali dei rapporti.
- Simulazione completa: due HDD riusciti, uno SSD riuscito, un errore HDD di lettura; rapporti HTML e JSON salvati e marcati SIMULAZIONE.
- Verifica reale della GUI in un display virtuale Linux: due loghi corretti, selezione e protezione del sistema, progressione SSD, pulsanti di avvio e conferma visibili con finestra 900×600. Il collaudo DPI e Windows resta necessario.
- Loghi originali preservati byte per byte; caricamento PNG completo con Pillow e ridimensionamento Lanczos al posto del sottocampionamento Tk. Logo CpV a 120 pixel alla densità base, con raster adattato al display.

La GUI è stata ricontrollata su display virtuale Linux, conservando le funzioni della 0.4.1: Seleziona lotto include i quattro esempi ammessi e lascia escluso il sistema, uno SSD senza metodo supportato è escluso e mostra la motivazione, il secondo clic annulla la selezione e il controllo è disabilitato durante il lavoro. La finestra ridotta e la conferma mantengono i pulsanti visibili.

I tre test aggiunti usano file reali temporanei: un HDD viene cancellato e verificato mentre un secondo resta in attesa di verifica; il registro del primo è già sul disco prima della conclusione del lotto. Un errore nel salvataggio del registro viene segnalato senza alterare l'esito della cancellazione o perdere il rapporto finale. Un SSD non supportato viene registrato come bloccato, con conteggi nulli e senza aprire una sessione.

I test esistenti coprono capacità e ultimo blocco, settori 512/4096, scrittura/rilettura integrali, errori e trasferimenti corti, annullamento, protezioni, identità, seriali USB, ATA/SAT IDENTIFY, accesso esclusivo, ritentativi e mantenimento offline dopo errori.

I nuovi test verificano capacità SSD e parole IDENTIFY non valide, sicurezza ATA, firme/registri a 48 bit, CDB SAT-16 e direzione dati, risposte incomplete/errori, metodi mancanti e NVMe escluso, protezioni, seriale cambiato, stato Sanitize prima di avviare, congelamento e lavoro già in corso, vecchio successo non riutilizzato dopo un comando rifiutato, annullamento dopo l'avvio seguito fino al completamento, sequenza password/prepare/enhanced erase, DPAPI fallita prima di impostare la password, registro cifrato conservato su errore, rapporti SSD con conteggi nulli e recupero senza erase né attestazione di cancellazione.

Questi risultati dimostrano il comportamento nei casi simulati. Non verificano firmware, passaggio dei comandi attraverso docking/driver, DPAPI reale o cancellazione fisica della memoria NAND. L'EXE 0.5.2 non è stato costruito o collaudato su Windows nell'ambiente automatico di sviluppo. Non è una certificazione NIST/Purge.

## Aggiornamenti firmati: prove eseguite

I 27 test usano chiavi Ed25519 generate in cartelle temporanee, firme reali e risposte HTTP simulate. Sono stati verificati:

- Firma corretta; rifiuto di metadati alterati, firma o chiave errata, campi duplicati, prodotto/piattaforma/repository/versione diversi, limiti di dimensione e protocollo avviatore.
- Ordinamento numerico delle versioni; esclusione di versioni vecchie, bozze, release non pubblicate, beta dal canale stabile, versioni già respinte e asset duplicati, mancanti o provenienti da percorsi estranei.
- Restrizione HTTPS e host di distribuzione; pacchetti corrotti o troncati rifiutati senza cambiare l'installazione attiva.
- Rifiuto di traversal, percorsi Windows ambigui, nomi riservati, collisioni tra maiuscole/minuscole, collegamenti simbolici, sovrapposizione file/cartelle ed espansione eccessiva.
- Installazione in una cartella separata, attivazione atomica, conservazione di programma precedente, impostazioni e rapporti; nessuna sovrascrittura di una versione esistente.
- Annullamento, assenza di rete e errore nel salvataggio del riferimento attivo: versione precedente ancora utilizzabile. Ripristino dopo un errore di avvio della versione nuova, che viene esclusa dai successivi controlli.
- Produzione degli allegati partendo da una cartella Windows simulata, firma verificabile e nessuna chiave privata negli ZIP. Rifiuto della compilazione con una chiave privata diversa dalla pubblica già associata al progetto.

Gli eseguibili delle prove di packaging sono file fittizi con intestazione MZ e **non vengono eseguiti**. Questi test non dimostrano che un EXE Windows sia stato compilato. Nelle prove automatiche non sono state create o pubblicate GitHub Release. L'attivazione per i colleghi richiede la procedura in `AGGIORNAMENTI_GITHUB.md`.

La finestra reale dell’avviatore è stata provata su display virtuale Linux: aggiornamento firmato con pacchetto simulato e ripiego offline sulla versione installata, senza avviare processi o accedere a dischi.

La GUI reale è stata verificata anche con densità Tk equivalenti a 100%, 150% e 200% su display virtuale Linux: logo CpV rispettivamente a circa 120, 180 e 240 pixel, pulsanti di avvio/conferma visibili alle dimensioni minime corrispondenti. Questa è una prova del layout e della scelta delle risorse, non di Windows DPI, del manifest o di una configurazione multimonitor.

## Rapporti 0.5.1: verifiche documentali

Cinque nuovi test verificano che successi, errori, blocchi e interruzioni non generino una firma, una validazione umana o una certificazione GDPR/Purge; gli SSD conservano i conteggi nulli e l'esito nativo. Sono stati verificati il collegamento esatto tra identificativo del lotto, record progressivi e rapporto finale, l'impronta SHA-256 del JSON mostrata nell'HTML, il collegamento al JSON dell'esempio incluso, l'escape dei dati e il rifiuto di identificativi che potrebbero alterare i percorsi di salvataggio.

I campi da completare sulla copia finale restano vuoti. Non vengono registrati nomi, firme o autorizzazioni non forniti. Queste verifiche riguardano il software e i documenti: non sono una valutazione legale dell'intero servizio, una firma qualificata, una prova di collaudo Windows o una certificazione dell'efficacia fisica sui dischi.

## Rapporti 0.5.2: impaginazione accessibile

Due schede di compilazione con etichette da 18 punti e righe da 12 mm; identificativo del rapporto su ciascuna scheda, campi separati e ampie firme. Anteprima A4 ottenuta dall'HTML con WeasyPrint 70.0 e controllata su pagine rasterizzate. Il PDF è un'anteprima di esempio, non una nuova funzione di esportazione automatica nell'EXE. La stampa reale da browser Windows resta da verificare.

Il test ZIP ostile conserva ora i nomi originali anche quando Python su Windows normalizza i separatori durante la creazione dell'archivio. La nuova regressione prova le combinazioni di separatori di lettura e scrittura. Restano attivi tutti i controlli degli aggiornamenti; non cambia il motore di cancellazione.

Riscontro del responsabile del 16 ottobre 2026: Andrea ha riferito compilazione riuscita della 0.5.1 su Windows con Python 3.15 e prova positiva della GUI, della simulazione e del rapporto. Si tratta di un riscontro d'uso, non di una prova di cancellazione su hardware reale e non della compilazione della 0.5.2.

## Collaudo Windows da eseguire

Il responsabile tecnico usa unità prive di dati da conservare. Iniziare con un solo SSD SATA prima di lavorare sulle 25 unità ricevute.

| Prova | Risultato necessario |
| --- | --- |
| GUI e simulazione | Due loghi, pulsanti di avvio e conferma visibili, lista scorrevole; esiti attesi. Provare DPI 125%, 150%, 200%. |
| Rilevamento | Modello, seriale, firmware, capacità e metodi corrispondenti; Windows/EFI/paging/programma/rapporti protetti, nessuna modifica ai dischi. |
| HDD USB e SATA | Scrittura, flush e rilettura completi su dischi di prova; protezioni conservate. |
| SSD Block Erase | Stato leggibile prima dell'avvio, comando accettato, progresso e completamento confermati; metodo nel rapporto. |
| SSD Enhanced Security Erase | DPAPI reale, registro prima della password; completamento confermato, sicurezza ATA disabilitata, registro rimosso. |
| Metodo o collegamento indisponibile | Esito non positivo; nessun ripiego sulla sovrascrittura HDD. |
| Guasto/interruzione SSD | Nessun falso successo; registro e profilo conservati quando necessari; collaudo con tecnico in grado di gestire il disco. |
| Recupero | Stesso PC/profilo originario, processo precedente chiuso, seriale e numero ricontrollati; rimozione password senza attestare la cancellazione. |
| Gruppo misto e più docking | Coda rispettata, progresso/esiti indipendenti, nessun avvio automatico dei nuovi dischi. |
| Seleziona lotto | Unità protette, ambigue o non ammesse escluse; una sola conferma iniziale. |
| Registri progressivi e lavoro prolungato | JSON disponibili per ciascun lavoro concluso prima del riepilogo; corretta segnalazione di errori di salvataggio. Alimentazione, ventilazione e impostazioni Windows verificate sulla postazione reale. |
| Cambio disco o identità ambigua | Blocco prima di inviare comandi distruttivi. |
| EXE senza Python | Intera installazione con AvviaDejavu.exe, _internal, versioni e attiva.json; UAC, demo, diagnostica e rapporti funzionanti sul secondo PC. |
| Aggiornamento reale | Pubblicare una prima release e una successiva firmate con la stessa chiave; verifica automatica, attivazione nuova versione, nessuna modifica a rapporti o impostazioni. Provare beta e stable. |
| Problemi di rete e pacchetto | Offline, timeout, proxy, download interrotto o firma errata: avvio della versione precedente, errore nel registro. |
| Processo elevato e seconda apertura | Avviatore aperto per tutta la vita del processo reale elevato; seconda apertura fermata nella stessa sessione. Nessun aggiornamento durante un lotto. Annullare UAC non deve respingere una versione valida. |
| Errore della nuova versione | Codice di uscita non zero dopo il primo aggiornamento: riferimento ripristinato per l'avvio successivo, nessuna ripartenza automatica di un lavoro. |
| Rapporto e consegna | Identificativi, seriali, metodi ed esiti corretti; HTML stampabile/PDF dal browser, impronta confrontabile col JSON, campi manuali leggibili. Validazione e firma esterne secondo l'incarico; conservare gli originali. |
| Bootstrap e chiavi | Chiave privata fuori dal progetto e dai pacchetti; pubblica corretta incorporata; seconda compilazione con la stessa chiave. Eventuali avvisi SmartScreen e antivirus valutati sulla postazione. |

Per ogni modello/firmware/collegamento annotare Windows, controller, metodo, durata ed esito. Confrontare con strumenti indipendenti e indicazioni del produttore. Prima di dichiarare Purge occorrono una validazione specifica e requisiti concordati con il donatore; il solo messaggio di successo non basta.

## Ripetere i test simulati

```console
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python prova_motore.py --rapporti esempi_rapporti
```

Il build esegue questi test prima di compilare l'EXE; non avvia cancellazioni su dischi reali.
