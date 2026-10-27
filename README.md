# Dejavu Disk Tool

Programma Windows per il Progetto Dejavu di Credere per Vedere OdV: interfaccia italiana per la cancellazione di HDD e SSD SATA compatibili, tramite USB o SATA interno, con protezione delle unità in uso e rapporti per disco.

**0.5.5-beta**: corregge le caselle di selezione che diventavano indisponibili a ogni rilevamento automatico. Durante il controllo periodico si possono selezionare i dischi; l'avvio attende la conclusione del controllo. Le righe invariate conservano selezione e focus. Se un disco cambia identità o non supera più i controlli, la selezione viene rimossa. Restano il riconoscimento USB della 0.5.4, le correzioni delle DLL, i rapporti accessibili, i loghi e gli aggiornamenti firmati. Agli operatori non serve Python.

**SSD in verifica:** dopo una prova della 0.5.4 su due SSD Samsung, uno non è più stato rilevato dalla docking. La causa è ancora da accertare; questa correzione dell'interfaccia non risolve né diagnostica quel problema. Sulla configurazione interessata sospendere le cancellazioni SSD e procedere con i soli controlli di rilevamento.

- [Istruzioni e limiti del programma](LEGGIMI_PRIMA.md)
- [Prima configurazione GitHub e aggiornamenti delle postazioni](AGGIORNAMENTI_GITHUB.md)
- [Rapporti, riferimenti normativi e firma del responsabile](RAPPORTI_E_RIFERIMENTI.md)
- [Guida degli operatori](GUIDA_MAURO_RINNA.html)
- [Verifiche eseguite e collaudo Windows necessario](VALIDAZIONE.md)

## Preparazione su Windows

Con Python 3.12–3.15 a 64 bit aprire `Crea_EXE.cmd`, sul PC del responsabile. Il comando esegue i test, crea la chiave di rilascio se è la prima compilazione, costruisce l'applicazione e l'avviatore e prepara gli allegati firmati nella cartella `release`. Per aggiornare i sorgenti già compilati alla 0.5.5 seguire `AGGIORNA_ALLA_0.5.5.txt`.

Distribuire `DejavuDiskTool-Installazione-Windows-x64.zip` e avviare **AvviaDejavu.exe**. Prima dell'uso operativo seguire il collaudo Windows: questa distribuzione contiene sorgenti, non un EXE già costruito o validato su hardware.

## Sviluppo e simulazione

```console
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py --demo
```

Su Windows `Prova_interfaccia.cmd` prepara automaticamente un ambiente dei sorgenti e apre la simulazione. Non apre dischi fisici. Il codice degli aggiornamenti non importa il motore di cancellazione.

HDD: sovrascrittura dello spazio esposto al PC e rilettura integrale. SSD SATA: soltanto metodi nativi supportati e verificati; nessun ripiego sulla sovrascrittura HDD. Un esito nativo positivo non è una certificazione Purge: consultare i limiti e la validazione richiesta.

Non pubblicare chiavi private, diagnostiche, rapporti o registri di recupero SSD. La chiave Ed25519 privata rimane nel profilo del responsabile, fuori da questo repository. Il programma non carica su GitHub dati dei dischi o rapporti.
