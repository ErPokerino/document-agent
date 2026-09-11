# Processors e LLM — anteprima locale

Sviluppo approvato per la pubblicazione sul remoto.

## Cosa provare

1. Aprire **Processors**: i processori già configurati sono nel catalogo. Usare
   All, OCR, Layout Parser e Custom Extractor oppure cercare un nome/ID/progetto.
2. Aprire **Details & versions**, poi **Check metadata & versions**. La verifica
   legge Google Cloud senza inviare documenti; mostra stato, versione predefinita,
   versioni disponibili e momento del controllo. Il controllo di metadati non
   certifica che sia consentita un’estrazione.
3. In **Pipelines**, aprire una pipeline esistente. Ogni step Document AI ha
   **Processor** e **Version**. Scegliere una versione e salvare per applicarla;
   Processor default segue il default di Google Cloud. I nuovi step richiedono
   una scelta esplicita del processore.
4. In **LLM**, passare da Local ad API: la scelta del modello non cambia.
   Il filtro Reads rimane; On disk compare solo in Local e conserva il valore
   quando si ritorna alla scheda. Il modello selezionato è sempre indicato.
5. **Settings** contiene l’aspetto. Connessione Document AI e tariffe sono in
   **Processors → Connection and pricing**.

## Comportamenti e limiti

- Registrare un processore aggiunge un riferimento locale a una risorsa Google
  esistente; non crea, addestra, distribuisce o modifica risorse nel cloud.
- Il nome è modificabile. Progetto, regione, tipo e ID non sono modificabili dopo
  la registrazione: una risorsa differente va registrata separatamente.
- Un processore usato da pipeline salvate non può essere rimosso dal catalogo.
  La rimozione di una registrazione non elimina il processore su Google Cloud.
- Le credenziali restano condivise attraverso il file di service account locale.
  Un progetto diverso richiede che quell’account abbia i permessi necessari.
- I nuovi run Lab conservano riferimenti concreti indipendenti dal catalogo e
  versioni risolte quando i metadati sono disponibili. Analytics separa anche
  versioni OCR/Layout differenti. I dati storici non vengono ricostruiti a posteriori.
- Se la versione predefinita non è risolvibile, non si può garantirne la stabilità:
  scegliere una versione esplicita per confronti controllati.
- Il modello LLM rimane una scelta globale. La riorganizzazione non introduce
  modelli diversi per ciascuno step. Le tariffe Document AI restano per tipologia.

## Migrazione

Le impostazioni precedenti e gli override nei singoli step vengono importati
preservando progetto, regione, processore e versione. La migrazione è ripetibile;
conserva copie `.pre-processors.bak` dei file originali dentro `backend/data`,
che rimane esclusa da Git. I PDF, le etichette e i risultati storici non cambiano.

## Verifica

Test automatici su migrazione, isolamento dei riferimenti, compatibilità dei tipi,
versioni, rimozione di risorse in uso, paginazione dei metadati e aggiornamenti
indipendenti delle opzioni dello step. Verifiche browser su catalogo, metadati reali,
scelta della versione, Local/API e finestre strette. Nessuna nuova estrazione a
pagamento eseguita per la verifica dell’interfaccia.

Esito finale: 212 test frontend e 738 backend superati; TypeScript, ESLint e build
produzione completati. Verificate nel browser la selezione di una versione OCR e
la conservazione del riferimento al processore cambiando le opzioni OCR. Controllati
Local/API, metadati reali OCR/Custom Extractor e navigazione a 486 px senza overflow
della pagina. Le tre pipeline migrate mantengono gli stessi riferimenti concreti
e le stesse opzioni rispetto ai backup originali. App riavviata per il test utente.

Il riquadro CE nell’intestazione mostra una versione compatta (es. Foundation 3.1 Lite); il tooltip conserva nome del processore e versione completa. Lo stato LLM non viene mostrato come stato del Custom Extractor.
