# Models trained on the datasets

Training models from labelled documents, the algorithm registry, the model registry, and tuning data for remote models.

**Models** trains models from labelled datasets, keeps them in a registry and
offers them to pipelines as the **Trained model** step.

Training is four choices — algorithm, data, features, parameters — and the
algorithms come from a registry in `backend/app/training/algorithms.py`. Each
entry declares its family, the package it needs, its parameters with their
bounds and help, and how it fits, predicts, saves and loads; the UI draws the
cards and the parameter inputs from that description, so adding an algorithm
needs no frontend code.

| Family | Algorithms | Here |
|---|---|---|
| Neighbours | Nearest neighbour over TF-IDF | trains |
| Linear | Logistic regression | trains |
| Gradient boosting | LightGBM, XGBoost, CatBoost | train |
| Foundation models | TabPFN | listed as not installed: `pip install tabpfn` brings PyTorch |
| Foundation models | Jev (TypeSafe AI, hosted) | listed as not connected |

- **Nearest neighbour**: a new document takes the labels of the most similar
  labelled one, or the similarity-weighted vote of the *k* nearest; the
  similarity is the score and the Workspace names the document a value came
  from. It cannot answer with a class no labelled document carries.
- **Classifiers** (every other algorithm): one model per predicted field over
  shared features, the class probability as the score. A field whose labels
  hold one class answers that class without a model.
- **Features**: TF-IDF of the text (character or word n-grams), optionally
  reduced by truncated SVD — the default for trees and TabPFN, which work on a
  few hundred dense columns — and, for algorithms that take them, other fields
  as inputs: a number as itself, a date as year, month and day, anything else
  as one column per value met at least twice in training. Input fields are
  learned from labels and read at run time from what earlier steps extracted,
  so the step has to follow those steps.
- **Compare** shows every model per field, best cross-validated accuracy
  first, with the algorithm, the features and how the figure was measured.

TabPFN predicts in context, from its training rows, so what is stored for it
is those rows as arrays. Jev returns a typed answer with probabilities to a
question about a text; it would answer a categorical field without training
here, once DocuFlow reaches the service.

- **Text read the same way.** Training reads each document with the reading
  steps of a chosen pipeline — those before its first step that fills fields —
  and records them. Pipelines warns when a step serves the model text read by
  other steps. Stored Document AI readings are reused, and the form states
  before training whether any document will be sent to Google.
- **No scoring on seen documents.** A model records the hash of every document
  it learned from, and a Lab run over a dataset containing any of them is
  refused. A temporal split learns only from documents whose own date label
  falls before a chosen day, leaving the later ones for a Lab dataset.
- **Validation** is the same for every algorithm, so the figures can share a
  table: five-fold cross-validation (one fold per document below five), every
  copy of one file kept in the same fold, and each fold training the whole
  model again, vocabulary included. Accuracy and macro F1 per field. Models
  trained before this record leave-one-out and say so. Either describes
  documents like the training ones; a Lab run or an experiment over a separate
  dataset is the measurement.
- **Artefacts are immutable and addressed by content.** The id hashes the
  manifest and the files, so the pipeline step, and therefore the Lab
  fingerprint, changes whenever the model does. A model in use by a pipeline
  cannot be deleted.
- **Declarative files only.** A model is a manifest, the vocabulary as JSON,
  IDF weights, SVD components and matrices as NumPy arrays read with
  `allow_pickle=False`, labels and classes as JSON, and each algorithm's own
  data format: logistic weights as arrays, LightGBM's text model, XGBoost's
  JSON, CatBoost's `.cbm`. Export and import move it as a zip; an archive with
  any file its manifest and kind do not declare is refused, since a pickle
  would run its own code when loaded. A model trained with an algorithm that
  is not installed here is listed and cannot be used until it is.

**Fine-tuning examples** writes labelled datasets as supervised tuning data,
one JSON object per line, in the Gemini-on-Vertex `contents` format or as chat
messages. Each example is built by the code that builds Gemini's request at run
time — system instruction with entity lines and confidence rubric, user text
with page note and document text — and answers with the labels as the JSON
Gemini is asked for, so a tuned model learns the question DocuFlow actually
asks. Examples carry text read by a pipeline's reading steps, not page images.
A document without a label for a field the model is asked for is left out and
listed, rather than written with `null`.

Training jobs run in the background and are kept in memory; a backend restart
forgets the jobs, never the models or the exported files. **Training elsewhere** lists the remote
targets — Gemini supervised tuning on Vertex AI, Document AI custom processors,
Bedrock, Azure OpenAI — as not connected: tuning Gemini is offered on Vertex AI
rather than through the Gemini API key used in LLM, and needs a project, a
Cloud Storage bucket and a service account allowed to run tuning jobs.

## Why a score rather than a stated confidence

A model's own *high*, *medium* or *low* is not calibrated: what *high* means
depends on the model. A trained model's score — a similarity to the nearest
labelled document, or a class probability — is a number the Lab's coverage
curve can set against accuracy, which is what an automatic pass needs: accept
above the threshold, send the rest to review. The nearest document also answers
that question directly: if it was extracted correctly, a new document like it
can pass without a person.
