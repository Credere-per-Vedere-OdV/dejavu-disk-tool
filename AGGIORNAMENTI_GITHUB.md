# Aggiornamenti per le postazioni Dejavu

Versione 0.5.7-beta — 27 ottobre 2026.

## Destinazione predisposta

Organizzazione: https://github.com/Credere-per-Vedere-OdV

Repository proposto: `Credere-per-Vedere-OdV/dejavu-disk-tool`.

È la destinazione configurata nei sorgenti. Il repository è stato creato dal responsabile dell'associazione, non da questo pacchetto. Il repository è stato creato e verificato pubblico il 16 ottobre 2026: https://github.com/Credere-per-Vedere-OdV/dejavu-disk-tool . Alla verifica del 24 ottobre 2026 risultano presenti i sorgenti e la Release v0.5.3-beta, con tutti e quattro gli allegati. Questa fornitura contiene i sorgenti 0.5.7 da compilare su Windows e non pubblica automaticamente una release. Eventuali repository privati non sono visibili senza accesso autorizzato. Se si preferisce un nome diverso, cambiare `repository` in `assets/aggiornamenti.json` **prima della prima distribuzione**.

Questo avviatore scarica da un repository pubblico: agli operatori non servono account o password GitHub. Il codice distribuito e i pacchetti sono pubblici; rapporti, diagnostiche, registri SSD e chiavi private restano fuori dal repository. La distribuzione da repository privati richiede una successiva integrazione di autenticazione; non inserire token personali nell'EXE.

## Prima attivazione, sul PC del responsabile

1. Nell'organizzazione creare il repository pubblico `dejavu-disk-tool`. Caricare i sorgenti di questa cartella, con `main.py`, `assets`, `dejavu` e gli altri file **alla radice del repository**. Non caricare rapporti, diagnostiche o chiavi private. Il file `.gitignore` esclude i percorsi locali previsti.
2. Su un solo PC Windows 11 a 64 bit, con Python 3.12, 3.13, 3.14 o 3.15, aprire `Crea_EXE.cmd`. Installa nell'ambiente di compilazione Pillow, cryptography e PyInstaller, esegue i test e costruisce due programmi Windows.
3. Alla prima compilazione viene creata una chiave Ed25519 privata nel profilo del responsabile: `%LOCALAPPDATA%\CrederePerVedere\DejavuDiskTool\chiavi_rilascio\aggiornamenti-ed25519.pem`. **Non inviarla ai colleghi e non pubblicarla.** Conservarne un backup riservato: è necessaria per firmare gli aggiornamenti futuri. La sola chiave pubblica, non segreta, viene scritta in `assets/update_public_key.pem` e incorporata nell'avviatore.
4. Collaudare la cartella `release\DejavuDiskTool`: aprire `Prova_interfaccia.cmd`, poi il rilevamento senza cancellazione. Seguire `VALIDAZIONE.md` prima di operare sui dischi reali. A questo punto il repository può non avere release: il controllo non trova aggiornamenti e avvia la versione installata.
5. In GitHub aprire **Releases → Draft a new release**, usare il tag **`v0.5.7-beta`** sul commit corrispondente e allegare i quattro file indicati sotto. La release beta può essere marcata come prerelease; il canale configurato è `beta`. Pubblicare soltanto dopo il collaudo.
6. Su ogni postazione estrarre una volta `DejavuDiskTool-Installazione-Windows-x64.zip` in una cartella stabile e scrivibile sul disco di Windows, per esempio `%LOCALAPPDATA%\CrederePerVedere\DejavuDiskTool\programma`. Creare un collegamento sul desktop a **`AvviaDejavu.exe`**. Copiare tutta la cartella, inclusi `_internal`, `versioni`, `attiva.json` e `impostazioni.ini`. Non occorre Python sui PC degli operatori.

I sorgenti in questo ZIP **non sono un EXE Windows già compilato**. Non includono una chiave privata o una chiave pubblica già associata all'associazione: la coppia nasce sul PC del responsabile, senza segreti prodotti o conservati da terzi. Non è stato pubblicato nulla su GitHub durante la preparazione del pacchetto.

## File generati per ogni release

| File nella cartella `release` | Funzione |
| --- | --- |
| `DejavuDiskTool-Installazione-Windows-x64.zip` | Prima installazione sulle nuove postazioni: avviatore e versione corrente. |
| `DejavuDiskTool-Windows-x64.zip` | Aggiornamento del programma, con tutte le sue librerie e risorse. |
| `aggiornamento.json` | Versione, prodotto, repository, dimensione e SHA-256 del pacchetto. |
| `aggiornamento.sig` | Firma Ed25519 dei metadati: verificata prima di scaricare il programma. |

Allegare tutti e quattro alla stessa GitHub Release. Non rinominarli, non modificare i metadati dopo la firma e non sostituire file di una release già pubblicata. Per una correzione creare una nuova versione. Lo ZIP automatico “Source code” offerto da GitHub non è il pacchetto Windows per gli operatori.

## Correzione dell'avviatore 0.5.2

Il primo pacchetto Windows 0.5.2 era privo di `python3t.dll`, richiesta dall'estensione `_rust.pyd`. La verifica delle dipendenze del pacchetto pubblicato ha confermato l'omissione. Il controllo di firma/download degli aggiornamenti eseguito da Linux non verificava il caricamento delle DLL Windows.

La correzione immediata aggiunge in `DejavuDiskTool/_internal` la DLL originale di Python 3.15.0 x64, corrispondente byte per byte al runtime gia' distribuito. Non modifica EXE, chiavi, metadati firmati, configurazione o rapporti. La 0.5.3 include la correzione nella compilazione e un controllo preventivo sulle dipendenze. Distribuire il nuovo avviatore completo alle postazioni interessate: gli aggiornamenti automatici della sola app non sostituiscono i file dell'avviatore. Non sovrascrivere gli allegati della Release 0.5.2 con pacchetti ricompilati e firme diverse.

## Correzione del riconoscimento USB 0.5.4

La diagnostica reale del 24 ottobre conferma due Samsung SSD 850 PRO 128GB dietro una Sabrent Dual SATA Bridge: IDENTIFY SAT-16 disponibile e metodo Enhanced Security Erase dichiarato dai dischi. La 0.5.3 rifiutava l’associazione confrontando il seriale firmware con il seriale generico della docking. La 0.5.4 distingue i due ruoli, mostra l’identità del disco e conserva quella del bridge nella diagnostica. L’avviatore e il protocollo non cambiano: un avviatore 0.5.3 funzionante riceve l’app aggiornata senza reinstallazione. Per compilazione e prima prova vedere `AGGIORNA_ALLA_0.5.7.txt`. Il rilevamento non prova ancora l’esecuzione della cancellazione nativa tramite quella docking.

## Caselle durante il rilevamento: correzione 0.5.5

Il controllo periodico mantiene utilizzabili caselle e Seleziona lotto. L'avvio attende comunque il risultato; una selezione viene conservata soltanto a identità e ammissibilità confermate. Le righe invariate non sono ricreate. Restano il blocco durante rilevamento iniziale/manuale e cancellazione, la conferma e i controlli del motore. Per compilare e provare senza cancellare dischi seguire `AGGIORNA_ALLA_0.5.7.txt`. La correzione riguarda soltanto l'interfaccia; la causa dell'SSD Samsung non più rilevato è ancora in verifica. Prima della distribuzione operativa chiarire quel problema. Avviatore, chiavi e protocollo restano invariati.

## Limite ai tentativi: correzione 0.5.6

Dopo tre rilevamenti conclusi con errori o senza dischi non protetti, la ricerca automatica si sospende. Rileva dischi avvia un nuovo controllo e azzera il conteggio. Nessuna modifica a motori HDD/SSD, protezioni, avviatore e firma. Il limite non risolve l’assenza dei due HDD dagli elenchi Windows né il caso del Samsung non più rilevato. Per la prima prova seguire `AGGIORNA_ALLA_0.5.7.txt`. Preparare una nuova versione e non sostituire pacchetti firmati già pubblicati.

## Rimozione sicura USB: nuova funzione 0.5.7

Dopo tutte le cancellazioni e il salvataggio dei rapporti, l’app tenta l’espulsione delle docking supportate, rispettando i controlli di identità, unità protette, dischi non selezionati e veto Windows. Esito USB separato nei rapporti HTML/JSON, nessuna espulsione forzata, nessun comando di cancellazione modificato. I dischi SATA interni non vengono espulsi. Il processo USB ha un limite complessivo di 90 secondi e conserva i risultati già confermati. Questa funzione richiede un collaudo Windows/docking prima di pubblicare la nuova Release v0.5.7-beta. Avviatore, chiavi e protocollo rimangono invariati. Seguire `AGGIORNA_ALLA_0.5.7.txt`.

## Dal secondo aggiornamento

1. Applicare le modifiche e incrementare `__version__` in `dejavu/__init__.py`, per esempio `0.5.8-beta`. Sono supportati `X.Y.Z`, `X.Y.Z-beta` e `X.Y.Z-beta.N`.
2. Ricompilare sul PC del responsabile, che conserva la chiave originaria, e collaudare la nuova versione. Per usare un altro PC, trasferire la chiave con una procedura riservata, nel percorso previsto. In alternativa un ambiente di compilazione può riceverla attraverso `DEJAVU_SIGNING_KEY_PEM`. Non metterla in script, commit o ZIP.
3. Pubblicare una nuova Release con tag corrispondente, per esempio `v0.5.8-beta`, e i quattro nuovi allegati. Un commit o un tag da soli non attivano un aggiornamento; una release in bozza non viene distribuita.
4. Alla successiva apertura da **AvviaDejavu.exe**, le postazioni con Internet controllano fino a 30 release recenti, scelgono la versione successiva più alta ammessa dal canale, verificano firma e pacchetto, preparano una cartella nuova e la attivano. Nessun intervento sui singoli PC.

Non cambiare la chiave tra una release e la successiva: gli avviatori già distribuiti rifiuterebbero le nuove firme. Per ruotare la chiave, aggiornare l'avviatore o realizzare una procedura dedicata. La firma applicativa Ed25519 verifica il canale di aggiornamento; **non è una firma Authenticode Windows** e non elimina gli eventuali avvisi SmartScreen degli EXE non firmati con un certificato riconosciuto.

La preparazione delle release resta un compito centrale del responsabile. Non è incluso un workflow GitHub Actions già attivo e non vengono pubblicate automaticamente nuove versioni a ogni commit.

## Comportamento per gli operatori

- Un doppio clic sul collegamento; controllo e aggiornamento prima di richiedere i privilegi di amministratore e prima del rilevamento dei dischi.
- Se Internet o GitHub non sono disponibili, o il pacchetto non supera i controlli, viene usata la versione già installata. Il registro locale spiega il problema.
- Il controllo non seleziona dischi e non avvia cancellazioni. Restano selezione del lotto e conferma iniziale.
- Durante il lavoro non esistono controlli periodici o aggiornamenti in background. L'avviatore attende l'uscita del processo elevato. Un'altra apertura nella stessa sessione Windows viene fermata.
- Chiudere la finestra di controllo annulla l'avvio. La versione precedente non viene sovrascritta. Un'eventuale cartella completa rimasta dopo un arresto forzato richiede il controllo del responsabile, senza sostituzioni forzate.
- Il file `impostazioni.ini` **accanto ad AvviaDejavu.exe** rimane quello della postazione. Rapporti e registri SSD restano nel percorso Windows già usato dal programma.
- Se il nuovo programma termina con codice di errore nella prima apertura dopo l'aggiornamento, viene ripristinato il riferimento alla versione precedente per il prossimo avvio. Nessuna cancellazione viene riavviata automaticamente. Un blocco o una finestra che non risponde richiedono assistenza: il controllo non impone timeout al processo di cancellazione.

Avviare direttamente `versioni\...\DejavuDiskTool.exe` evita il controllo degli aggiornamenti. Anche i vecchi EXE non si aggiornano da soli: la prima sostituzione con questa installazione va fatta manualmente una volta. Per la manutenzione è disponibile `Avvia_senza_aggiornamenti.cmd`.

Il registro dell'avviatore è `%LOCALAPPDATA%\CrederePerVedere\DejavuDiskTool\aggiornamenti.log`. Le richieste a GitHub riguardano metadati pubblici e file del programma; non contengono seriali, contenuti dei dischi, rapporti o registri SSD. La richiesta di rete espone a GitHub i normali dati di connessione, come l'indirizzo IP.

## Limiti e collaudo necessario

Il pacchetto e il motore degli aggiornamenti sono stati verificati con file temporanei, firme reali Ed25519 e risposte di rete simulate. La 0.5.7 non è stata compilata su Windows nell’ambiente automatico di sviluppo. Le diagnostiche del responsabile confermano l’esecuzione della 0.5.4 su Windows 11 con Python 3.15. La causa dell’SSD non più rilevato dopo la prova nativa rimane da chiarire: sospendere le cancellazioni SSD sulla configurazione interessata e non distribuire questa correzione come soluzione a quel problema. Questi riscontri non sostituiscono il collaudo della nuova versione e dei dischi reali. UAC, attesa del processo elevato, mutex Windows, proxy/antivirus, download reali da GitHub e resa DPI richiedono il collaudo indicato in `VALIDAZIONE.md`.

L'avviatore è stabile e separato dal motore: aggiorna il programma e le relative librerie, **non se stesso**. Una modifica al protocollo o all'avviatore richiede una nuova installazione manuale dello stesso; gli aggiornamenti che dichiarano un protocollo superiore vengono rifiutati. Tutte le versioni vecchie vengono conservate, senza pulizia automatica: il responsabile può rimuovere quelle non più necessarie dopo il collaudo, a programma chiuso, lasciando attiva e precedente.

La singola sessione Windows viene coordinata con mutex; non è una gestione multiutente di un server. Per il laboratorio usare una sessione operativa alla volta. Nessun aggiornamento riprende lavori interrotti, cambia l'algoritmo scelto per un lavoro in corso o aggiunge una certificazione Purge.

## Riferimenti tecnici

- GitHub Releases/API: https://docs.github.com/en/rest/releases/releases
- Ed25519: https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/
- Attesa del processo elevato: https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexw
