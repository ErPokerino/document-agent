"""Train a model from labelled datasets with any algorithm, and measure it before keeping it.

Validation is the same for every algorithm, so their figures can sit in one
table: k-fold cross-validation over the training documents, five folds or one
per document when there are fewer, with every copy of one file kept in the same
fold — a copy in another fold would be its own best match. Each fold trains the
whole model again, vocabulary included, so nothing about a held-out document
leaks into the features it is judged with.

It describes documents like the training ones; a Lab run over a dataset kept
apart from training is the measurement, and the only kind the Lab will start
with this model in the pipeline.
"""

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Callable

from app.domain.models import EntityDefinition, KnnParameters, TextFeatures
from app.evaluation.classification import classification_report
from app.evaluation.scoring import FieldOutcome, values_match
from app.training import knn
from app.training.algorithms import Algorithm
from app.training.artifacts import ArtifactStore, StoredArtifact
from app.training.classifier import KIND as CLASSIFIER, ClassifierModel
from app.training.corpus import LabelledDocument, ReadDocument, before_cutoff

FOLDS = 5


def select_documents(
    documents: list[LabelledDocument],
    entities: list[str],
    cutoff_entity: str | None,
    cutoff_before: date | None,
) -> tuple[list[LabelledDocument], int]:
    """The documents to learn from, and how many a temporal cutoff left out.

    A document is kept when it is labelled for at least one target field and,
    with a cutoff, when its own label dates it before the cutoff. One with no
    date label cannot be placed in time and is left out with the rest.
    """
    labelled = [document for document in documents if any(entity in document.labels for entity in entities)]
    if not cutoff_entity or cutoff_before is None:
        return labelled, 0
    kept = [document for document in labelled if before_cutoff(document.labels, cutoff_entity, cutoff_before)]
    return kept, len(labelled) - len(kept)


def knn_parameters(text: TextFeatures, parameters: dict[str, Any]) -> KnnParameters:
    """A nearest-neighbour model's settings: the text features, plus how neighbours vote."""
    shared = text.model_dump(exclude={"reduce_to"})
    return KnnParameters(**shared, **parameters)


class Recipe:
    """How to train one model on some of the documents: what folds and the final fit share."""

    def __init__(
        self,
        algorithm: Algorithm,
        text: TextFeatures,
        parameters: dict[str, Any],
        targets: list[EntityDefinition],
        input_fields: list[EntityDefinition],
    ) -> None:
        self.algorithm = algorithm
        self.text = text
        self.parameters = parameters
        self.targets = targets
        self.input_fields = input_fields

    def labels(self, item: ReadDocument) -> dict[str, Any]:
        names = {entity.name for entity in self.targets}
        return {key: value for key, value in item.document.labels.items() if key in names}

    def inputs(self, item: ReadDocument) -> dict[str, Any]:
        return {entity.name: item.document.labels.get(entity.name) for entity in self.input_fields}

    def train(self, items: list[ReadDocument]) -> Any:
        if self.algorithm.id == "knn_tfidf":
            documents = [
                knn.TrainingDocument(item.document.dataset, item.document.name, item.document.sha256, self.labels(item))
                for item in items
            ]
            return knn.KnnModel.train([item.text for item in items], documents, knn_parameters(self.text, self.parameters))
        return ClassifierModel.train(
            self.algorithm, self.text, self.input_fields, [entity.name for entity in self.targets],
            [item.text for item in items], [self.inputs(item) for item in items],
            [self.labels(item) for item in items], self.parameters,
        )


def folds_for(items: list[ReadDocument], folds: int = FOLDS) -> list[list[int]]:
    """Positions per fold, copies of one file always together, the same every time."""
    hashes = sorted({item.document.sha256 for item in items}, key=lambda digest: hashlib.sha256(digest.encode()).hexdigest())
    count = min(folds, len(hashes))
    fold_of = {digest: position % count for position, digest in enumerate(hashes)}
    grouped: list[list[int]] = [[] for _ in range(count)]
    for position, item in enumerate(items):
        grouped[fold_of[item.document.sha256]].append(position)
    return grouped


def cross_validate(recipe: Recipe, items: list[ReadDocument], on_phase: Callable[[str], None] | None = None) -> dict[str, Any]:
    outcomes: dict[str, list[FieldOutcome]] = {entity.name: [] for entity in recipe.targets}
    folds = folds_for(items)
    for number, held_out in enumerate(folds, start=1):
        if on_phase is not None:
            on_phase(f"validating, fold {number} of {len(folds)}")
        training = [item for position, item in enumerate(items) if position not in set(held_out)]
        if len({item.document.sha256 for item in training}) < 1:
            continue
        try:
            model = recipe.train(training)
        except ValueError:
            # A fold too small to fit — one document, or one class — predicts
            # nothing; its documents count as unanswered rather than vanish.
            model = None
        for position in held_out:
            item = items[position]
            labels = recipe.labels(item)
            predicted = model.predict_all(item.text, list(labels), recipe.inputs(item)) if model is not None else {}
            for entity in recipe.targets:
                if entity.name not in labels:
                    continue
                prediction = predicted.get(entity.name)
                actual = prediction.value if prediction is not None else None
                outcomes[entity.name].append(
                    FieldOutcome(
                        entity=entity.name, expected=labels[entity.name], actual=actual, confidence="high",
                        matched=values_match(labels[entity.name], actual, entity),
                        score=prediction.score if prediction is not None else None,
                    )
                )
    measured: dict[str, Any] = {}
    for entity in recipe.targets:
        if not outcomes[entity.name]:
            continue
        report = classification_report(entity.name, outcomes[entity.name])
        measured[entity.name] = {
            "documents": report.documents,
            "accuracy": report.accuracy,
            "macro_f1": report.macro_f1,
            "classes": len(report.classes),
        }
    return {"method": f"{len(folds)}-fold cross-validation, grouped by file", "entities": measured}


def train_model(
    *,
    store: ArtifactStore,
    name: str,
    algorithm: Algorithm,
    read: list[ReadDocument],
    targets: list[EntityDefinition],
    input_fields: list[EntityDefinition],
    text: TextFeatures,
    parameters: dict[str, Any],
    training: dict[str, Any],
    on_phase: Callable[[str], None] | None = None,
) -> StoredArtifact:
    recipe = Recipe(algorithm, text, parameters, targets, input_fields)
    validation = cross_validate(recipe, read, on_phase)
    if on_phase is not None:
        on_phase("fitting on every document")
    model = recipe.train(read)
    common = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entities": [entity.name for entity in targets],
        "input": "text",
        "libraries": knn.library_versions(),
        "training": {
            **training,
            "documents": [
                {"dataset": item.document.dataset, "document": item.document.name, "sha256": item.document.sha256}
                for item in read
            ],
        },
        "validation": validation,
    }
    files = model.files()
    if algorithm.id == "knn_tfidf":
        manifest = {**common, "kind": knn.KIND, "algorithm": algorithm.id, "parameters": model.parameters.model_dump(mode="json")}
    else:
        manifest = {
            **common,
            "kind": CLASSIFIER,
            "algorithm": algorithm.id,
            "parameters": parameters,
            "text": text.model_dump(mode="json"),
            "input_fields": [entity.name for entity in input_fields],
            "files": sorted(files),
        }
    return store.save(manifest, files)


def progress_callback(job: Any) -> Callable[[int], None]:
    def advance(done: int) -> None:
        job.done = done

    return advance
