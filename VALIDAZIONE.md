# Validazione della beta 0.5.7

27 ottobre 2026 — Linux, Python 3.12 a 64 bit. Nessun Windows nativo disponibile e nessun disco reale aperto.

## Eseguito

- Compilazione sintattica dei sorgenti.
- 186 test unittest superati: 95 per motore e registri precedenti, 27 per gli aggiornamenti firmati, 6 per i rapporti, 5 per le dipendenze Windows, 19 per la GUI, 27 per identità/topologia/veto USB e 7 per l’ordine fra cancellazione, salvataggio ed espulsione.
- Simulazione completa: due HDD riusciti, uno SSD riuscito, un errore HDD di lettura; rapporti HTML e JSON salvati e marcati SIMULAZIONE.
- Verifica reale della GUI in un display virtuale Linux: due loghi corretti, selezione e protezione del sistema, progressione SSD, pulsanti di avvio e conferma visibili con finestra 900×600. Il collaudo DPI e Windows resta necessario.
- Loghi originali preservati byte per byte; caricamento PNG completo con Pillow e ridimensionamento Lanczos al posto del sottocampionamento Tk. Logo CpV a 120 pixel alla densità base, con raster adattato al display.

La GUI è stata ricontrollata su display virtuale Linux, conservando le funzioni della 0.4.1: Seleziona lotto include i quattro esempi ammessi e lascia escluso il sistema, uno SSD senza metodo supportato è escluso e mostra la motivazione, il secondo clic annulla la selezione e il controllo è disabilitato durante il lavoro. La finestra ridotta e la conferma mantengono i pulsanti visibili.

I tre test aggiunti usano file reali temporanei: un HDD viene cancellato e verificato mentre un secondo resta in attesa di verifica; il registro del primo è già sul disco prima della conclusione del lotto. Un errore nel salvataggio del registro viene segnalato senza alterare l'esito della cancellazione o perdere il rapporto finale. Un SSD non supportato viene registrato come bloccato, con conteggi nulli e senza aprire una sessione.

I test esistenti coprono capacità e ultimo blocco, settori 512/4096, scrittura/rilettura integrali, errori e trasferimenti corti, annullamento, protezioni, identità, seriali USB, ATA/SAT IDENTIFY, accesso esclusivo, ritentativi e mantenimento offline dopo errori.

I nuovi test verificano capacità SSD e parole IDENTIFY non valide, sicurezza ATA, firme/registri a 48 bit, CDB SAT-16 e direzione dati, risposte incomplete/errori, metodi mancanti e NVMe escluso, protezioni, seriale cambiato, stato Sanitize prima di avviare, congelamento e lavoro già in corso, vecchio successo non riutilizzato dopo un comando rifiutato, annullamento dopo l'avvio seguito fino al completamento, sequenza password/prepare/enhanced erase, DPAPI fallita prima di impostare la password, registro cifrato conservato su errore, rapporti SSD con conteggi nulli e recupero senza erase né attestazione di cancellazione.

Questi risultati dimostrano il comportamento nei casi simulati. Non verificano firmware, passaggio dei comandi attraverso docking/driver, DPAPI reale o cancellazione fisica della memoria NAND. L'EXE 0.5.7 non è stato costruito o collaudato su Windows nell'ambiente automatico di sviluppo. Non è una certificazione NIST/Purge.

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

## Avvio su un PC senza Python: correzione 0.5.3

17 ottobre 2026: il responsabile ha segnalato il mancato avvio della 0.5.2 su un altro Windows 11, con errore di caricamento di cryptography `_rust`. L'analisi statica delle importazioni PE dell'installer pubblicato ha individuato la dipendenza `python3t.dll`, assente nell'avviatore. Il runtime `python315.dll` distribuito coincide byte per byte con quello nell'archivio embeddable ufficiale Python 3.15.0 x64. Sono stati verificati SHA-256 dell'archivio rispetto alla pagina python.org, provenienza e compatibilità della DLL recuperata, e chiusura delle dipendenze Python di avviatore e app dopo l'aggiunta. Non è stato eseguito codice Windows durante questa verifica.

La compilazione ora raccoglie le DLL Stable ABI dall'interprete effettivo dell'ambiente di compilazione, distinguendo lo shim compatibile dal runtime free-threaded eventualmente installato insieme. Rifiuta un pacchetto che contenga estensioni con DLL Python mancanti. Cinque test riproducono l'omissione, verificano entrambe le disposizioni delle DLL, il rifiuto dell'architettura non x64 e dei PE troncati. Andrea ha successivamente confermato l’avvio corretto sul portatile dopo l’aggiunta della DLL. La Release 0.5.3-beta risulta pubblicata dal 17 ottobre; la diagnostica del 24 ottobre conferma l’esecuzione della 0.5.3 con Python 3.15.0 su Windows 11 Pro.

## Riconoscimento della docking USB: correzione 0.5.4

La diagnostica reale del 24 ottobre mostra due Samsung SSD 850 PRO 128GB, con firmware diversi, dietro una Sabrent Dual SATA Bridge (`VID_174C&PID_55AA`). Entrambi rispondono a SAT-16 IDENTIFY e dichiarano Enhanced Security Erase, senza blocchi ATA riportati. Il nome, seriale composto da zeri e UniqueId esposti da Windows appartengono al bridge e sono condivisi. La 0.5.3 rifiutava l’identità firmware perché il nome generico del bridge non corrispondeva al modello Samsung. La diagnostica della 0.5.3 non conservava separatamente il seriale firmware dei dischi bloccati.

La 0.5.4 accetta l’identità ATA sul singolo PhysicalDrive verificato quando Windows espone un nome generico SATA Bridge; richiede comunque un collegamento USB nativo coerente, tipo HDD/SSD confermato e seriale firmware non vuoto o composto da zeri. Mantiene il blocco per un modello Windows concreto in conflitto. Espone nella GUI l’identità del disco e conserva separatamente i metadati del bridge. Restano il rifiuto dei seriali firmware duplicati e i controlli di capacità, settori, numero fisico, unità protette e identità ricontrollata sul dispositivo aperto.

Sette nuove regressioni, senza accesso a dischi reali, riproducono due SSD uguali per modello/capacità con bridge condiviso e seriali firmware sintetici distinti, seriali firmware duplicati, identità/metodo mancanti o sicurezza ATA congelata, geometria incoerente, disco cambiato, seriale composto da zeri anche con un solo bersaglio e risposta IDENTIFY con seriale composto da zeri. I test precedenti sul modello di un altro disco, mancata identità e swap rimangono attivi.

Queste prove verificano il riconoscimento e le protezioni nel software. Non confermano ancora l’avvio, l’accettazione o il completamento di Enhanced Security Erase sulla docking fisica. Algoritmi HDD/SSD, avviatore, protocollo e chiavi degli aggiornamenti non sono stati modificati.

## Selezione durante il rilevamento: correzione 0.5.5

Il rilevamento automatico ogni 15 secondi usava lo stesso blocco della selezione previsto per il rilevamento iniziale e manuale. Il difetto è stato riprodotto eseguendo la nuova prova contro il codice originale 0.5.4: le caselle diventano disabilitate mentre il worker è in attesa. La prova passa con la correzione.

Dieci regressioni verificano selezione individuale e del lotto durante un worker reale in attesa, avvio bloccato fino al risultato, conservazione delle righe e delle spunte a dati invariati, disco cambiato nello stesso numero fisico senza trasferimento della spunta, perdita della selezione quando cambiano protezione o ammissibilità, errore di rilevamento, nuova unità non selezionata, rilevamento manuale e iniziale bloccanti, rispetto di selezioni/conferma/lavoro/esiti e azzeramento degli esiti dopo una richiesta manuale. I dati e i widget dei test sono simulati; nessun disco fisico viene aperto.

La verifica è stata ripetuta con Tk reale su display virtuale Linux, mettendo in pausa il worker di rilevamento: le caselle e Seleziona lotto restano azionabili, il sistema è protetto, l'avvio è bloccato fino al risultato e le stesse righe conservano le spunte dopo il controllo. I pulsanti della conferma sono visibili a 900×600. Questa prova non sostituisce il collaudo Windows/DPI.

Algoritmi e comandi HDD/SSD, identificazione nativa, avviatore, protocollo degli aggiornamenti e loghi sono invariati rispetto alla 0.5.4.

## Tentativi di rilevamento: correzione 0.5.6

La diagnostica del 27 ottobre sui due HDD mostra soltanto l'unità di sistema sia nell'inventario Get-Disk sia in Win32_DiskDrive, senza errori del rilevamento principale e con raccolta PnP completata. Non permette di attribuire l'assenza degli HDD alla precedente cancellazione con DFTools. La GUI ripeteva il controllo ogni 15 secondi anche quando Windows non mostrava altri dischi.

La ricerca automatica ora si sospende dopo tre rilevamenti consecutivi conclusi con errori o senza unità non protette. Rileva dischi azzera il conteggio e avvia una nuova serie limitata; un rilevamento valido con unità non protette azzera il conteggio. Si contano i controlli conclusi: non viene forzata l'interruzione di richieste già in attesa di Windows o del driver. Il limite non rende visibile un dispositivo assente dagli elenchi Windows e non avvia cancellazioni.

Sette regressioni verificano: pausa dopo tre risultati con il solo sistema e assenza di nuove scansioni ai successivi tick; pausa dopo errori; ripresa manuale con nuove unità non selezionate; azzeramento del conteggio dopo un rilevamento valido; nuovo limite dopo una ripresa manuale ancora senza unità; protezione non confermata anche con dischi visibili; errore dell'inventario che mantiene disabilitate selezione e avvio anche con il flag di protezione impostato. Il caso del solo sistema è stato eseguito anche sul codice 0.5.5 e riproduce il quarto tentativo che la correzione impedisce.

Con Tk reale su display virtuale Linux è stato verificato il messaggio di pausa dopo tre controlli, il pulsante Rileva dischi disponibile, l'assenza di nuovi rilevamenti automatici e la ripresa manuale con unità riconosciute ma senza spunta. Restano verificati i controlli grafici della 0.5.5. Algoritmi HDD/SSD, inventario Windows e comandi nativi sono invariati rispetto alla 0.5.5. Nessun disco fisico è stato aperto.

## Rimozione sicura automatica USB: 0.5.7

La nuova funzione viene eseguita soltanto dopo il termine di tutti i worker, la chiusura di tutte le sessioni e il salvataggio dei registri e dei rapporti. Non cambia i comandi di cancellazione HDD/SSD. Un inventario completo e protetto viene ricostruito nel processo ausiliario, insieme all’associazione Win32_DiskDrive/PnP. Il target deve essere un nodo USB VID/PID con servizio USBSTOR/UASPSTOR e capacità rimovibile, distinto da hub e controller. Sono contati tutti i figli disco del ramo nativo, compresi quelli non presenti in Get-Disk. Sono richiesti tutti i dischi del ramo nel lotto, identità firmware coerenti, esito positivo e assenza di avvisi. Un dispositivo composto o non riconosciuto viene lasciato collegato.

La sola operazione che cambia stato è CM_Request_Device_EjectW, una volta per dispositivo. I veto di Windows restano rispettati; nessuna chiamata force-remove, disable o eject-media è usata come ripiego. La fase USB intera è limitata a 90 secondi nel processo ausiliario; il processo principale rimane reattivo. Un timeout non prova l’assenza di un’operazione PnP già in corso: l’esito rimane non confermato e richiede controllo manuale. Le espulsioni già confermate dal processo sono conservate progressivamente. Non sono impartiti comandi di spegnimento della docking o dei SATA interni.

Le 27 prove USB usano identificativi sintetici con due LUN Sabrent e seriale bridge composto da zeri, nodi PnP simulati e risposte native simulate. Coprono dischi non scelti, protetti, mancanti, cambiati, duplicati, figli non censiti, inventari discordi, più docking, SATA escluso, hub/controller/funzioni composte escluse, veto, ramo cambiato, proprietà UTF-16/REG_DWORD, firme ctypes, processo sorgente/congelato, timeout con risultati parziali e percorso interno senza mutex o GUI. Sette prove del lotto verificano con veri file temporanei che il secondo worker sia concluso e i rapporti esistano prima dell’espulsione, oltre a errori di salvataggio, annullamento, simulazione, SATA e insuccesso PnP. Due prove GUI e una prova rapporto distinguono cancellazione e rimozione e preservano i dati tecnici.

La GUI è stata eseguita con Tk reale su display virtuale Linux: completato un lotto di soli file temporanei con due HDD e uno SSD riusciti e un errore HDD atteso, rapporto HTML/JSON e rimozione marcata SIMULAZIONE. Verificati anche il messaggio di espulsione confermata e quello di rifiuto mediante risposte sintetiche consegnate al gestore Tk, con pulsante Apri rapporto visibile a 900×600. Le conferme, la selezione stabile e la pausa dopo tre rilevamenti restano funzionanti. Non è stata eseguita alcuna API PnP Windows o espulsione fisica.

Fonti primarie consultate il 27 ottobre 2026:
- Microsoft, CM_Request_Device_EjectW: https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_request_device_ejectw
- Microsoft, capacità rimovibile: https://learn.microsoft.com/en-us/windows-hardware/drivers/install/overview-of-the-removable-device-capability
- Microsoft, PNP_VETO_TYPE: https://learn.microsoft.com/en-us/windows/win32/api/cfg/ne-cfg-pnp_veto_type
- Header Microsoft WinSDK cfgmgr32.h nel repository microsoft/win32metadata: verificati i valori delle proprietà, delle capacità e dei codici CR.

Prima della distribuzione collaudare sul PC Windows e sulla docking reale: due dischi autorizzati completati, una seconda unità non selezionata che impedisce l’espulsione dello stesso dispositivo, più docking e un eventuale rifiuto Windows. Verificare che dopo l’espulsione/spegnimento si possano sostituire i dischi, riaccendere e rilevare il nuovo gruppo. Una cancellazione riuscita nella vecchia versione non collauda la nuova richiesta PnP.

## Riscontro hardware ancora da chiarire

Il responsabile ha fornito un rapporto 0.5.4 con esito nativo positivo per due SSD Samsung e ha successivamente segnalato la mancata rilevazione di uno di essi. Le nuove diagnostiche mostrano il Samsung rimasto rilevabile; il responsabile riferisce anche il riconoscimento di un Kingston nuovo. Questi dati non stabiliscono la causa della scomparsa del primo SSD né dimostrano l'efficacia fisica della cancellazione. La correzione 0.5.5 riguarda la selezione grafica e non risolve il problema del disco mancante. Sospendere le cancellazioni SSD sulla configurazione interessata e verificare il disco con un collegamento indipendente prima della distribuzione operativa.

## Collaudo Windows da eseguire

Il responsabile tecnico usa unità prive di dati da conservare. Iniziare con un solo SSD SATA prima di lavorare sulle 25 unità ricevute.

| Prova | Risultato necessario |
| --- | --- |
| GUI e simulazione | Due loghi, pulsanti di avvio e conferma visibili, lista scorrevole; esiti attesi. Provare DPI 125%, 150%, 200%. |
| Selezione e controllo periodico | Senza selezioni attendere almeno un minuto: caselle e Seleziona lotto restano azionabili durante gli aggiornamenti automatici. Selezionare durante un controllo e verificare che la spunta resti; avvio bloccato fino al risultato. Sistema sempre protetto. Nessuna cancellazione necessaria per questa prova. |
| Nessun disco aggiuntivo o errori | Dopo tre controlli conclusi, ricerca automatica sospesa e Rileva dischi disponibile. Collegare una unità di prova e premere Rileva dischi: rilevamento ripreso, nessuna selezione o cancellazione automatica. |
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
