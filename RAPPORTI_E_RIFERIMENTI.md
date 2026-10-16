# Rapporti, riferimenti e attestazione dell'attività

Versione 0.5.2-beta — verifica delle fonti: 16 ottobre 2026.

## Che cosa rilascia il programma

Un **rapporto tecnico delle operazioni di cancellazione**, con identificativo del lotto, modello e seriale del supporto, firmware disponibile, metodo effettivo, date dell'attività, conteggi HDD o esito nativo SSD, errori e avvisi. Il rapporto finale HTML è stampabile; contiene il riferimento al JSON originale e la sua impronta SHA-256. Ogni JSON progressivo per disco riporta lo stesso identificativo del lotto e un identificativo specifico dell'unità.

Il rapporto registra anche gli esiti non riusciti. La sua esistenza non significa che un disco sia stato cancellato o sia idoneo alla consegna. Le simulazioni rimangono esplicitamente identificate.

La 0.5.1 aggiunge i riferimenti di contesto seguenti; **non dichiara che l'associazione o il software abbiano ottenuto certificazioni**.

| Riferimento | Significato del richiamo |
| --- | --- |
| GDPR, Reg. (UE) 2016/679, artt. 5(2), 24 e 32 | Documentare le misure e valutare una sicurezza adeguata al rischio. Non stabilisce un unico algoritmo valido per ogni supporto o situazione. |
| Garante, provvedimento 13 ottobre 2008, doc. web 1571514 | Principi di protezione nella dismissione e nel reimpiego; possibilità di attestare le operazioni eseguite da soggetti incaricati. È antecedente al GDPR e va letto nel quadro vigente, tenendo conto dell'evoluzione tecnologica. Non viene dichiarata l'applicazione letterale delle sue vecchie tecniche. |
| NIST SP 800-88 Rev. 2, settembre 2025, sez. 4.5–4.6 e appendice C | Riferimento tecnico per distinguere verifica e validazione e strutturare le registrazioni per supporto. Non è una legge italiana o europea e il richiamo non equivale a una certificazione NIST. |

I provvedimenti precedenti al GDPR restano applicabili nei limiti di compatibilità con il quadro vigente (d.lgs. 101/2018, art. 22, comma 4). Non si ricavano obblighi attuali di un numero fisso di passaggi dalle vecchie indicazioni tecniche del 2008. Il metodo deve essere adeguato al supporto e al rischio: i riferimenti in un rapporto non sostituiscono questa valutazione.

## Completare e approvare il rapporto

La stampa prevede campi per affidante/provenienza, riferimento dell'incarico e autorizzazione, operatore, postazione, firma e validazione del responsabile. Sono **campi vuoti da compilare sulla copia finale**, non firme o approvazioni create dal programma. I campi compilati sulla carta o nel PDF non vengono acquisiti nel JSON: conservare anche quella copia finale, collegata all'identificativo del rapporto.

La verifica automatica conferma ciò che il programma ha registrato. La validazione organizzativa decide se quell'esito sia sufficiente per la destinazione prevista, tenendo conto di dati, metodo, modello/firmware, collegamento, errori e requisiti del donatore. Il JSON indica sempre `human_validation: NOT_RECORDED`: questa versione non acquisisce una validazione elettronica del responsabile. Non seleziona automaticamente “accettata” sulla stampa.

Per gli HDD il motore registra la sovrascrittura e la rilettura dello spazio esposto al PC. Per gli SSD registra il metodo nativo e l'esito del dispositivo; non misura tutta la NAND. Nessuno dei due risultati genera automaticamente un'attestazione Purge. Restano necessari collaudo Windows e validazione del procedimento: vedere `VALIDAZIONE.md`.

## Compilazione manuale e stampa leggibile

La 0.5.2 aggiunge due schede A4 dedicate: compilazione dell'operatore e validazione del responsabile. Le etichette sono da 18 punti, con caratteri scuri su fondo bianco. I campi occupano la larghezza disponibile, le righe sono distanziate di 12 mm e le aree per provenienza, incarico, riserve e responsabile hanno più righe. Nome dell'operatore e postazione sono separati; le firme hanno una zona distinta dalla data. Entrambe le schede riportano l'identificativo del rapporto e l'eventuale dicitura di simulazione.

Stampare in A4 verticale al 100%, con margini definiti dal documento, senza ridurre per far stare l'intero rapporto in una pagina. I contenuti tecnici possono occupare più pagine; le ultime due sono dedicate alla scrittura. Conservare tutte le pagine insieme. Il programma continua a produrre HTML e JSON; il PDF si ottiene dalla stampa del browser. I rapporti già emessi restano quelli originali: il nuovo impaginato vale per i nuovi rapporti.

## Valore del documento, firma e data

Un documento elettronico non è privo di effetti giuridici solo perché elettronico (eIDAS, art. 46). Il suo concreto valore probatorio dipende dal documento e dalle circostanze. Aggiungere un elenco di norme o la parola “certificato” non dimostra conformità o veridicità dell'esito.

Per rafforzare attribuzione e integrità si può produrre il PDF dalla stampa HTML, completarlo e sottoscriverlo con **firma elettronica qualificata / firma digitale del responsabile**, tramite un servizio o dispositivo abilitato. La firma qualificata ha effetti equivalenti alla firma autografa (eIDAS, art. 25(2)); non dimostra, da sola, che il disco sia tecnicamente irrecuperabile. Per la data è eventualmente possibile usare una marca temporale qualificata, ai sensi dell'art. 41 eIDAS. Conservare il documento originale firmato e il JSON associato secondo la procedura concordata; non basta conservarne una semplice stampa o una foto.

**Funzioni non comprese:** generazione diretta di PDF, firma qualificata, marca temporale qualificata e conservazione a norma automatica. Il rapporto HTML si può stampare su carta o salvare in PDF dal browser. La data del programma proviene dall'orologio del PC. Il SHA-256 permette il confronto del JSON se il valore di riferimento è attendibile, ma da solo non garantisce autore, data o assenza di modifiche successive. La firma Ed25519 degli aggiornamenti del programma è separata e non è una firma qualificata dei rapporti.

## Incarichi per banche, aziende o PA

Concordare **prima della consegna dei supporti** l'autorizzazione alla cancellazione, gli identificativi e la provenienza, il livello richiesto, le tecniche accettate e la gestione delle unità che non superano i controlli. Il titolare dei dati deve valutare e accettare il procedimento, con il supporto del suo referente privacy. Il DPO svolge una funzione consultiva: non sostituisce la responsabilità decisionale del titolare. Se l'associazione tratta dati per conto dell'ente come responsabile, occorre disciplinare il rapporto ai sensi dell'art. 28 GDPR; il ruolo non viene deciso automaticamente dal software o dal fatto che i PC siano donati.

Tenere traccia della presa in carico e della destinazione finale. Per documenti destinati a un singolo donatore, usare lotti separati o fornire solo le registrazioni delle sue unità, senza includere informazioni di altri affidanti. Un disco bloccato, fallito o interrotto richiede un nuovo intervento o una diversa destinazione concordata, non un'attestazione positiva. Definire con il donatore la conservazione e l'accesso ai rapporti: non pubblicarli sul repository GitHub.

Prima di presentare questo servizio come prestazione con specifiche garanzie contrattuali, fare verificare al referente privacy/legale dell'associazione il modello di incarico, il rapporto e il procedimento realmente collaudato. Il software conserva evidenze tecniche; non sostituisce tale accordo o attribuisce qualifiche professionali.

## Fonti ufficiali

- GDPR e guida del Garante: https://www.garanteprivacy.it/regolamentoue
- Principi e misure basate sul rischio: https://www.garanteprivacy.it/web/guest/home/principi-fondamentali-del-trattamento
- Provvedimento italiano: https://www.garanteprivacy.it/web/guest/home/docweb/-/docweb-display/docweb/1571514
- NIST SP 800-88 Rev. 2: https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-88r2.pdf
- eIDAS, Regolamento (UE) 910/2014, come modificato: https://eur-lex.europa.eu/eli/reg/2014/910/oj/ita
- Firma e data qualificata, AgID: https://www.agid.gov.it/it/piattaforme/firma-elettronica-qualificata
