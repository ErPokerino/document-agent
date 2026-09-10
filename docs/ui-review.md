# Revisione UI e testi — 10 settembre 2026

Revisione approvata per la pubblicazione. Interfaccia mantenuta in inglese.

## Esito dell’analisi

La struttura delle sezioni è coerente. I problemi più chiari erano nella leggibilità
delle spiegazioni, nei tooltip e in testi che descrivevano ogni estrazione come una
chiamata a un LLM. La revisione riguarda Workspace, Extraction e prompt, Pipelines,
Master Data e regole, Datasets, Lab, LLM e Settings. Comprende testi visibili,
help contestuali e attributi title; non costituisce una certificazione di accessibilità.

## Modifiche da valutare

| Area | Prima | Ora |
| --- | --- | --- |
| Help contestuale | Testo che poteva essere tagliato da tabelle e pannelli; attivazione soprattutto al passaggio del mouse | Tooltip fuori dai contenitori, posizione adattata allo spazio, apertura con hover/focus/tap, chiusura con Escape o clic esterno, bersaglio di 24 px e focus visibile |
| Leggibilità | Diversi testi di supporto a 8–9 px | Descrizioni e aiuti principali a 11 px, tooltip a 12 px con interlinea maggiore |
| Workspace | “Model ready” anche se non caricato | Stato testuale coerente con la disponibilità |
| Intestazione | Custom Extractor portava a LLM; anche un LLM poteva mostrare “Version unavailable” | Custom Extractor apre Pipelines; versione riservata al processore |
| Datasets | Draft bloccato dall’assenza di LLM anche quando la pipeline non ne richiede uno | Disponibilità coerente con la pipeline; tooltip descrive l’estrazione tramite pipeline |
| Extraction | Descrizioni riferite esclusivamente al modello | Campi estratti descritti rispetto a modello o Custom Extractor |
| Analytics | “Left is cheaper” anche per tempo e token; definizione Pareto troppo restrittiva | Testo coerente con l’asse; definizione che considera anche uguaglianza su una misura |
| Analytics | Approcci senza misura omessi senza avviso | Conteggio degli approcci visibili quando mancano misure |
| Compare | Evidenziazione Pareto con colore chiaro fisso | Colore basato sul tema; selettore corretto per usare variabili CSS esistenti |
| Past runs | Help di “Score without” prometteva di modificare ogni accuratezza | Ambito esplicito: punteggi della tabella ed export, esclusi filtri e Analytics |
| Pipelines | Zoom 1.35 indicato come circa 130 DPI | Circa 97 DPI, coerente con la scala PDF di 72 punti per pollice |
| Prompt e configurazione | Immagini date per scontate; vantaggi di costo/velocità presentati come universali | Testo o immagini secondo pipeline; descrizioni delle capacità senza promesse |

I grafici mantengono dimensioni, numerazione e dettagli su richiesta: non vengono
aggiunte etichette permanenti ai punti. Le informazioni nuove sulle misure mancanti
compaiono solo quando servono. Il riepilogo del motore può andare a capo.

## Miglioramenti successivi da discutere

- **Uniformare l’esclusione dei campi tra Runs e Analytics.** Oggi è una vista locale
  dei punteggi. Per estenderla servono regole esplicite per soglie, confronti e export.
- **Distinguere configurazione e verifica dei servizi.** Una chiave presente non
  dimostra che il servizio sia raggiungibile o autorizzato; utile uno stato verificato
  con data dell’ultimo controllo.
- **Confronti sperimentali più rigorosi.** Raggruppare per motore, versione, dataset
  e pipeline non equivale a confrontare configurazioni identiche: prompt e altre
  impostazioni possono differire. Un confronto per configurazione completa richiede
  una scelta funzionale, oltre a nuove etichette.
- **Azioni di salvataggio e verifica.** Settings spiega che Verify usa i valori già
  salvati; rendere visibile lo stato delle modifiche pendenti vicino a Verify sarebbe
  più immediato, ma merita un intervento coerente tra tutte le sezioni.

## Verifica

- TypeScript ed ESLint: superati.
- Suite esistente: 209 test frontend e 716 test backend superati.
- Build di produzione: completata; app riavviata e verificata nel browser.
- Tutte le sezioni principali aperte a 1280 px; nessun overflow orizzontale della pagina rilevato.
- Analytics verificato anche a 680 px: tooltip dentro il viewport, grafico e filtri contenuti nella pagina.
- Verificate apertura con clic, persistenza durante la lettura, apertura da tastiera e chiusura con Escape.
- Verificati testo dinamico dell’asse costi e avviso sulle misure mancanti (3 approcci visualizzati su 34 nei dati presenti).
- La correzione della disponibilità Draft senza LLM è verificata sul percorso del codice e sulla compilazione; non è stata avviata una nuova estrazione Custom Extractor.
- A finestre strette le tacche dei grafici restano dense: una vista mobile dedicata richiederebbe un intervento ulteriore. Non è stata svolta una prova con screen reader o dispositivo touch fisico.
Non vengono avviate estrazioni a pagamento né modificate etichette o configurazioni
persistenti durante la verifica visiva.
