# Piano: Claude Sonnet 5.5, Claude Opus 5.5 e Grok 4.7 su Cloud

Verifica del 6 ottobre 2026. Repository: `ErPokerino/document-agent`, branch
`cloud`, commit `66c9f9f07607ac3581bd737ded249ee2747e3e05`, recuperato dal remoto.
Progetto Google Cloud: `tutoral-498710`.

L'integrazione è fattibile tramite i modelli partner gestiti di Gemini Enterprise
Agent Platform / Model Garden. La base Cloud dispone già di identità del runtime,
Vertex AI, worker e persistenza. Servono due adapter di inferenza, l'estensione
del catalogo e un registro dei consumi per singola chiamata. Quest'ultimo è
necessario per applicare correttamente cache, reasoning, endpoint e soglie di
contesto, conservando il costo storico.

## 1. Stato del progetto e punti da estendere

| Area | Stato osservato nel branch Cloud | Intervento |
|---|---|---|
| Autenticazione | `services/gcp_runtime.py` ottiene e rinnova il token dal metadata server | Riutilizzare per entrambi gli adapter |
| Gemini | `services/gemini.py` usa `generateContent`; il deployment sceglie `eu` | Mantenere il percorso esistente e separare le location dei partner |
| Estrattori | `ExtractionProvider` restituisce gli stessi campi validati; `pipeline/steps.py:43` sceglie il client | Registrare Claude e Grok dietro la stessa interfaccia |
| Catalogo e readiness | `api/deps.py:298`, `routes/models.py`, `routes/settings.py` sono ancora specifici per Gemini | Catalogo partner e disponibilità per modello, senza bloccare gli altri provider |
| Contratti | Settings, profili, estrazioni, valutazioni ed esperimenti ammettono `lm_studio`, `gemini`, `model_server` | Aggiungere un provider per Model Garden e rigenerare i tipi frontend |
| Costi | `domain/settings.py:11` contiene due tariffe; `lib/cost.ts:17` moltiplica token aggregati per le tariffe attuali | Calcolo backend per chiamata e tariffe versionate |
| Chiamate aggiuntive | Le regole fornitore sommano già i token; un secondo passo `ExtractEntities` sovrascrive `inference_stats` | Accumulare eventi indipendenti per tutti i passi |
| Errori | `evaluation/runner.py:94` salva il fallimento senza i consumi; il parsing può fallire dopo una risposta fatturabile | Salvare usage e tentativo anche quando l'estrazione fallisce |
| Analytics / CSV | `app/lab/lab.tsx` e `lib/runs-csv.ts` considerano fatturabile soltanto `provider == gemini` | Usare costo e completezza restituiti dal backend |
| Riproducibilità | I profili registrano thinking e parametri; progetto, publisher ed endpoint LLM non sono congelati nel profilo | Includerli nello snapshot e nel fingerprint |

Le vecchie segnalazioni sul progetto locale non descrivono tutte lo stato attuale:
il branch analizzato contiene già le correzioni per regole fornitore, pagine
Custom Extractor e `usage_complete`. Va estesa questa base, senza reintrodurre
il trattamento dei consumi mancanti come zero.

## 2. Catalogo e scelta degli endpoint

| Modello | ID del modello | API | Endpoint proposto |
|---|---|---|---|
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | Anthropic Messages su `:rawPredict` | `eu` |
| Claude Opus 5.5 | `claude-opus-5-5` | Anthropic Messages su `:rawPredict` | `eu` |
| Grok 4.7 | `grok-4.7`, selettore API `xai/grok-4.7` | OpenAI-compatible Chat Completions | `global`, con `us` configurabile |

Claude è GA e supporta testo, immagini e PDF, con endpoint EU, US e global.
Grok è Preview, supporta testo e immagini, endpoint US/global e quote fisse;
non offre batch. Per la prima integrazione si riutilizzano testo e pagine
renderizzate dalle pipeline esistenti. Il PDF diretto Claude è un'estensione
separata, perché deve rispettare il limite pagine della pipeline.
Fonti: [Sonnet](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/sonnet-5-5),
[Opus](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/opus-5-5),
[Grok](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/grok/grok-4-7).

Gli URL sono costruiti dal progetto e dalla location:

```text
Claude EU:
https://aiplatform.eu.rep.googleapis.com/v1/projects/{project}/locations/eu/publishers/anthropic/models/{model}:rawPredict

Grok global:
https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi/chat/completions

Grok US:
https://aiplatform.us.rep.googleapis.com/v1/projects/{project}/locations/us/endpoints/openapi/chat/completions
```

Il progetto e la location dei partner devono essere configurazioni proprie,
con lo stesso progetto di Gemini come default. Nessun cambio automatico di
endpoint in caso di errore: altererebbe costo e località di elaborazione.
Per Grok la UI deve indicare la località effettiva; un requisito esclusivo EU
impedirebbe di utilizzarlo allo stato attuale. Le API restano Google Cloud e
la fatturazione resta sul progetto.
[Endpoint partner](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/use-partner-models).

## 3. Adapter e integrazione applicativa

Introdurre un catalogo `HostedModelSpec` con ID, provider applicativo, publisher,
selettore API, location consentite, stato GA/Preview, modalità e controlli
supportati. Una scelta pratica è aggiungere `provider="model_garden"` ai
contratti e distinguere i partner tramite `publisher`; `gemini` continua a
identificare le configurazioni e le run esistenti.

Creare `ClaudeVertexClient` e `GrokVertexClient`, con HTTP e autenticazione
confinati ai moduli adapter. Riutilizzare prompt, semantica dei campi derivati,
nota sulle pagine escluse, confidence, limiti sui valori e `validate_result`.

Claude usa il payload Messages, immagini come blocchi base64 e
`anthropic_version="vertex-2023-10-16"`. Usare JSON strutturato tramite
`output_config.format`, con adattamento delle limitazioni dello schema e
validazione applicativa. Leggere i blocchi di testo finali separatamente dai
blocchi thinking. In particolare, Opus 5.5 ha thinking adattivo sempre attivo
e rifiuta tool call forzate: il vecchio espediente di forzare un tool estrattore
non deve diventare il meccanismo per ottenere il JSON. Sonnet 5.5 prevede anche
`between_tools`. I controlli offerti devono seguire le capacità del modello.
Fonti: [JSON strutturato](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide),
[Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5).

Grok usa messaggi Chat Completions, immagini `image_url` e schema JSON
supportato da quel trasporto. Il client normalizza testo finale, stop reason,
usage e reasoning. Mantenere le chiamate senza strumenti esterni, coerentemente
con il compito di estrazione corrente.
[Schema Grok](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/grok/capabilities/structured-output).

Registrare il provider in Workspace, Lab, Experiments e worker: la selezione
deve essere ricostruibile da snapshot. Usare `ProviderError` come gestione
comune anche nel runner, che oggi cattura esplicitamente gli errori Gemini.
Un 403, un modello non disponibile o un 429 devono lasciare visibili gli altri
modelli e riportare il problema del singolo accesso.

## 4. Pricing di riferimento

USD per milione di token, inferenza online. Fonte tariffaria esclusiva:
[pricing Google della piattaforma / Model Garden](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
verificato il 6 ottobre 2026.

| Modello / endpoint | Input ordinario | Output | Cache hit | Cache write 5 min | Cache write 1 h |
|---|---:|---:|---:|---:|---:|
| Sonnet 5.5 global | 2,00 | 10,00 | 0,20 | 2,50 | 4,00 |
| Sonnet 5.5 EU/US | 2,20 | 11,00 | 0,22 | 2,75 | 4,40 |
| Opus 5.5 global | 4,00 | 20,00 | 0,20 | 5,00 | 8,00 |
| Opus 5.5 EU/US | 4,40 | 22,00 | 0,22 | 5,50 | 8,80 |
| Grok 4.7, contesto <= 200.000 | 2,00 | 6,00 | 0,50 | — | — |
| Grok 4.7, contesto > 200.000 | 4,00 | 12,00 | 1,00 | — | — |

Grok usa la fascia del contesto completo di ciascuna richiesta per tutti i
token. Le due fasce input/output Claude 5.5 coincidono. Celle mancanti restano
sconosciute. Osservazione: i valori batch Opus global non corrispondono a una
riduzione del 50%; verificarli prima di implementare il batch.

## 5. Registro consumi e costo storico

Inserire una riga persistente per ciascun tentativo di inferenza, con:

- run/evaluation/job/documento, passo pipeline, ID chiamata e tentativo;
- provider, publisher, modello richiesto e restituito, progetto, location,
  tipo di endpoint e timestamp;
- token input ordinari, cache letta, cache scritta con durata, output
  fatturabile, reasoning come dettaglio, usage originale e completezza;
- stato HTTP, esito estrazione, request ID quando disponibile;
- versione della tariffa, data verifica, URL fonte, valuta e costo calcolato.

Normalizzare i contatori con regole specifiche del provider. Per Claude, input
ordinario e contatori cache vanno trattati come categorie distinte. Per Grok,
se il totale input include la cache, sottrarre la cache prima di applicare la
tariffa input ordinaria. Il collaudo reale Grok del 2026-10-06 ha mostrato
reasoning separato da completion_tokens: 588 input, 24 risposta, 72 reasoning,
684 totali. Normalizzare l'output con total_tokens - prompt_tokens quando
disponibile, senza duplicare reasoning se è già incluso. Conservare l'usage
originale per verificare queste trasformazioni.

Formula della chiamata, dopo la normalizzazione:

```text
costo = (input_ordinario * tariffa_input
       + cache_letta * tariffa_cache_hit
       + cache_scritta_5m * tariffa_write_5m
       + cache_scritta_1h * tariffa_write_1h
       + output_fatturabile * tariffa_output) / 1.000.000
```

Usare `Decimal` per le somme backend. Sommare le chiamate dopo aver calcolato
ciascuna: un totale di 210.000 token prodotto da due richieste da 100.000 e
110.000 non è una richiesta nella fascia lunga. Includere passi LLM ripetuti,
regole fornitore, retry e risposte fatturabili poi rifiutate dal parser.
Persistenza appena ricevuto usage, prima della validazione del risultato;
un timeout/cancel con consumo non noto rende il totale incompleto.

Esporre costo stimato alla data della chiamata, subtotale noto e stato
`complete / partial / unknown`. Distinguere la completezza dei consumi dalla
disponibilità della tariffa. Con tariffe mancanti il costo totale resta
sconosciuto anche quando i token sono noti. Una successiva ritariffazione può
essere una vista esplicita, distinta dal costo storico congelato.

Le migrazioni conservano tariffe personalizzate e tariffe eliminate. Le run
legacy non ricevono un breakdown cache o una tariffa storica inventati:
conservano l'attuale stima da tariffe correnti, marcata come tale. Per nuove
run Gemini su Vertex verificare la fonte tariffaria del trasporto effettivo,
poiché i default attuali derivano dalla Gemini API.

Il totale inferenza comprende le pagine Document AI effettivamente chiamate;
una lettura riusata dalla cache applicativa non ne aggiunge. Cloud Run, Cloud
SQL, storage e altre risorse restano costi infrastrutturali separati. Il ledger
è una stima riproducibile: il consuntivo deriva dal billing Google, riconciliato
con le aggregazioni per modello e periodo.

## 6. Permessi e quote: cosa è stato verificato

| Controllo nel progetto reale | Risultato |
|---|---|
| Billing | Attivo |
| `aiplatform.googleapis.com` | Abilitata |
| Identità servizio `docuflow` | `docuflow-run@tutoral-498710.iam.gserviceaccount.com` |
| Identità job `docuflow-worker` | Lo stesso service account |
| Ruolo inferenza del service account | `roles/aiplatform.user`, già assegnato |
| Utente gcloud | Owner del progetto; il ruolo include predict e permessi procurement/consensi |
| Consumer Procurement API | Non compare tra le API abilitate nella verifica mirata |
| Grok global, quota richiesta/minuto | 10 |
| Grok global, quota input/minuto | 1.135.000 token |
| Grok global, quota output/minuto | 10.500 token |
| Controllo gratuito Claude, count-tokens EU | Entrambi i modelli: 429 `RESOURCE_EXHAUSTED`, base model `anthropic-count-tokens` |

Le quote Grok provengono da Service Usage del progetto, e prevalgono sui
default della documentazione. Non attestano da sole l'accettazione dei termini
o il successo di una chiamata. Per Claude il 429 riguarda il servizio di
conteggio: non prova che la quota di inferenza sia esaurita o che i modelli
siano disabilitati. I campi di quota richiesta per count-tokens restituiti
dall'API sono assenti; non sono stati interpretati come uno zero confermato.

Prima del collaudo di inferenza verificare l'abilitazione di ciascuna scheda
Model Garden nel progetto e i relativi termini partner. Per l'abilitazione
Google documenta `roles/consumerprocurement.entitlementManager`; per chiamare
il modello documenta `aiplatform.endpoints.predict`, coperto dal ruolo runtime
già presente. Consumer Procurement riguarda l'abilitazione/gestione: la sua
assenza non dimostra che un modello già abilitato non sia utilizzabile. Il
service account runtime deve continuare a ricevere i soli permessi di uso.
[Requisiti Google](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/use-partner-models).

Per usare il preflight gratuito Claude in EU bisogna risolvere il 429 osservato,
controllando la quota dedicata. È possibile rendere il conteggio preventivo
opzionale: i consumi consuntivi devono comunque venire dalla risposta di
inferenza. Il conteggio token è gratuito.
[Count tokens](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/count-tokens).

## 7. Sequenza di implementazione e verifica

| Fase | Risultato concreto | Criterio di chiusura |
|---|---|---|
| 1. Contratti e catalogo | Catalogo, provider, configurazione separata, snapshot endpoint e tariffe | Migrazioni compatibili; tipi rigenerati; vecchie run leggibili |
| 2. Consumi e persistenza | Ledger e calcolo backend, usati anche da Gemini | Ogni chiamata registrata, anche fallita; costi storici stabili |
| 3. Adapter Claude e Grok | Estrazione testo/immagini nello stesso contratto | Test HTTP simulati per payload, schema, reasoning, usage, 403/404/429 e truncation |
| 4. Workspace e Lab | Selezione LLM, controlli per modello, esperimenti misti, CSV e Analytics | Costo coerente in dettaglio, confronto, export e retry |
| 5. Accesso e collaudo Cloud | Verifica schede/termini, quote, singola estrazione sintetica per modello | Risposta strutturata valida e ledger con usage reale da `docuflow-run` |
| 6. Valutazione e rilascio | Esperimento su dataset congelato con Gemini e i tre partner | Accuratezza, latenza e costo/documento confrontabili; deploy app e worker coerenti |

Applicare un limite richieste e token condiviso tra app e worker: un limiter
solo in memoria non copre processi diversi. Per Grok partire dalla quota
effettiva di 10 RPM e verificare anche input/output TPM. Gestire `Retry-After`
e backoff limitato per 429/503, con tentativi registrati e nessuna sostituzione
automatica del modello. Terminare chiaramente il job per accessi non autorizzati.

Test economici necessari: soglie Grok 199.999/200.000/200.001, richieste
aggregate che attraversano 200.000, cache mista e cache write con durata,
reasoning contato una volta, due passi LLM, regola fornitore, parsing fallito,
cancel/timeout, retry senza duplicati, tariffa assente, modifica delle tariffe,
run legacy e parità tra SQLite e PostgreSQL. Verificare costo invariato fra
API, Lab e CSV.

Eseguire `npm run types:generate`, `npm test` e `npm run build` al termine
dell'implementazione. Aggiornare `docs/architecture.md`,
`docs/features/llm-and-processors.md`, `docs/features/lab.md`,
`docs/deployment.md`, `ROADMAP.md` e una decisione sul costo storico. Il piano
è basato su ispezione del codice, documentazione corrente e controlli Cloud
di accesso/quote; il collaudo di inferenza resta nella fase 5.

## 8. File previsti

- Nuovi adapter e catalogo in `backend/app/services/`; nuovi contratti
  usage/pricing in `backend/app/domain/` e servizio di calcolo backend.
- `backend/app/config.py`, `api/deps.py`, `api/routes/models.py`,
  `settings.py`, `documents.py`, `evaluations.py`, `experiments.py`.
- `backend/app/pipeline/engine.py`, `steps.py`, `services/settings_store.py`,
  `services/run_store.py`, `evaluation/store.py`, `evaluation/runner.py`,
  moduli di snapshot/fingerprint e migrazioni DB.
- `app/llm/llm.tsx`, componenti Workspace/Lab/Experiments, filtri,
  `lib/cost.ts`, `lib/runs-csv.ts`, `lib/types.ts` generato.
- `deploy/gcp/personal.env`, `deploy/gcp/deploy.sh` per propagare la stessa
  configurazione al servizio e al worker; preflight documentato per il target.
- Test adapter, migrazioni, ledger, costi, esperimenti e CSV.

Le fasi 1–4 costituiscono una modifica trasversale di dimensione medio-grande;
un adapter isolato sarebbe soltanto una parte della consegna. Il primo
rilascio riguarda inferenza online e tracciamento completo; batch, PDF diretto
Claude e strumenti agentici aggiuntivi restano estensioni successive.
