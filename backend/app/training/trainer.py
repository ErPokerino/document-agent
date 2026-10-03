"""Train a nearest-neighbour model from labelled datasets, and measure it before keeping it.

Validation is leave-one-out over the training documents: each one predicted
from all the others. It is what the model would score on documents like these
that it had not seen — a measure, not a guarantee, and no substitute for a Lab
run over a dataset kept apart from training, which is the only kind of run the
Lab will start with this model in the pipeline.
"""

from datetime import date, datetime, timezone
from typing import Any, Callable

from app.domain.models import EntityDefinition
from app.evaluation.classification import classification_report
from app.evaluation.scoring import FieldOutcome, values_match
from app.training import knn
from app.training.artifacts import ArtifactStore, StoredArtifact
from app.training.corpus import LabelledDocument, ReadDocument, before_cutoff


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


def validate(model: knn.KnnModel, entities: list[EntityDefinition]) -> dict[str, Any]:
    measured: dict[str, Any] = {}
    for entity in entities:
        outcomes = []
        for expected, prediction in model.leave_one_out(entity.name):
            actual = prediction.value if prediction is not None else None
            outcomes.append(
                FieldOutcome(
                    entity=entity.name,
                    expected=expected,
                    actual=actual,
                    confidence="high",
                    matched=values_match(expected, actual, entity),
                    score=prediction.score if prediction is not None else None,
                )
            )
        if not outcomes:
            continue
        report = classification_report(entity.name, outcomes)
        measured[entity.name] = {
            "documents": report.documents,
            "accuracy": report.accuracy,
            "macro_f1": report.macro_f1,
            "classes": len(report.classes),
        }
    return {"method": "leave_one_out", "entities": measured}


def train_knn(
    *,
    store: ArtifactStore,
    name: str,
    read: list[ReadDocument],
    entities: list[EntityDefinition],
    parameters: knn.KnnParameters,
    training: dict[str, Any],
) -> StoredArtifact:
    names = [entity.name for entity in entities]
    documents = [
        knn.TrainingDocument(
            dataset=item.document.dataset,
            document=item.document.name,
            sha256=item.document.sha256,
            labels={key: value for key, value in item.document.labels.items() if key in names},
        )
        for item in read
    ]
    model = knn.KnnModel.train([item.text for item in read], documents, parameters)
    manifest = {
        "kind": knn.KIND,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entities": names,
        "input": "text",
        "parameters": parameters.model_dump(mode="json"),
        "libraries": knn.library_versions(),
        "training": {
            **training,
            "documents": [
                {"dataset": document.dataset, "document": document.document, "sha256": document.sha256}
                for document in documents
            ],
        },
        "validation": validate(model, entities),
    }
    return store.save(manifest, model.files())


def progress_callback(job: Any) -> Callable[[int], None]:
    def advance(done: int) -> None:
        job.done = done

    return advance
