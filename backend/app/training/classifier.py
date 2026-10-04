"""A classifier per field, over one shared set of features, trained with any algorithm.

Each predicted field has its own classes, so each gets its own model — a head —
over the same features. A field whose labels hold a single class gets no
model at all: it always answers that class, which is all the labels can teach.

`None` is a class like the others: a document labelled as carrying no value
for a field teaches the model that such documents exist.
"""

import json
from typing import Any

import numpy as np

from app.domain.models import EntityDefinition, TextFeatures, category_key
from app.training.algorithms import Algorithm, algorithm as find_algorithm
from app.training.features import Featurizer
from app.training.knn import Prediction

KIND = "classifier"
NONE_KEY = "\u0000none"


def _key(value: Any) -> str:
    return NONE_KEY if value is None else category_key(value)


class ClassifierModel:
    def __init__(
        self,
        algorithm: Algorithm,
        featurizer: Featurizer,
        heads: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        self.algorithm = algorithm
        self.featurizer = featurizer
        # entity -> {"classes": [shown values], "model": fitted or None}
        self.heads = heads
        self.parameters = parameters
        # Only a nearest-neighbour vote has more than one voter.
        self.votes = 1

    @classmethod
    def train(
        cls,
        algorithm: Algorithm,
        spec: TextFeatures,
        input_fields: list[EntityDefinition],
        entities: list[str],
        texts: list[str],
        rows: list[dict[str, Any]],
        labels: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> "ClassifierModel":
        featurizer = Featurizer(spec, input_fields)
        features = featurizer.fit_transform(texts, rows)
        heads: dict[str, dict[str, Any]] = {}
        for entity in entities:
            index = [position for position, document in enumerate(labels) if entity in document]
            if not index:
                continue
            shown: dict[str, Any] = {}
            for position in index:
                shown.setdefault(_key(labels[position][entity]), labels[position][entity])
            keys = sorted(shown)
            if len(keys) == 1:
                heads[entity] = {"classes": [shown[keys[0]]], "model": None}
                continue
            target = np.array([keys.index(_key(labels[position][entity])) for position in index])
            selected = features[index]
            heads[entity] = {
                "classes": [shown[key] for key in keys],
                "model": algorithm.fit(selected, target, len(keys), parameters),
            }
        return cls(algorithm, featurizer, heads, parameters)

    def predict_all(self, text: str, entities: list[str], fields: dict[str, Any] | None = None) -> dict[str, Prediction | None]:
        features = self.featurizer.transform([text], [fields or {}])
        predicted: dict[str, Prediction | None] = {}
        for entity in entities:
            head = self.heads.get(entity)
            if head is None:
                predicted[entity] = None
                continue
            if head["model"] is None:
                predicted[entity] = Prediction(value=head["classes"][0], score=1.0, agreement=1.0, nearest=None)
                continue
            probabilities = self.algorithm.predict(head["model"], features)[0]
            best = int(np.argmax(probabilities))
            score = round(float(probabilities[best]), 4)
            predicted[entity] = Prediction(value=head["classes"][best], score=score, agreement=score, nearest=None)
        return predicted

    # -- storage -----------------------------------------------------------------

    def files(self) -> dict[str, bytes]:
        stored = dict(self.featurizer.files())
        for entity, head in self.heads.items():
            stored[f"{entity}.classes.json"] = json.dumps(head["classes"], ensure_ascii=False).encode("utf-8")
            if head["model"] is not None:
                stored.update(self.algorithm.save(head["model"], entity))
        return stored

    @classmethod
    def from_files(cls, files: dict[str, bytes], manifest: dict[str, Any]) -> "ClassifierModel":
        algorithm = find_algorithm(str(manifest["algorithm"]))
        if algorithm.status() != "available":
            raise ValueError(f"This model was trained with {algorithm.label}, which cannot run here: {algorithm.install or 'not connected'}")
        spec = TextFeatures.model_validate(manifest["text"])
        parameters = dict(manifest.get("parameters") or {})
        featurizer = Featurizer.from_files(files, spec)
        heads = {}
        for entity in manifest["entities"]:
            name = f"{entity}.classes.json"
            if name not in files:
                continue
            classes = json.loads(files[name].decode("utf-8"))
            model = algorithm.load(files, entity, parameters) if len(classes) > 1 else None
            heads[entity] = {"classes": classes, "model": model}
        return cls(algorithm, featurizer, heads, parameters)


def classifier_files_allowed(name: str, entities: list[str]) -> bool:
    """Whether a file belongs in a classifier artefact: never anything that could be a pickle."""
    if name in ("vocabulary.json", "idf.npy", "svd.npy", "fields.json"):
        return True
    for entity in entities:
        if not name.startswith(f"{entity}."):
            continue
        suffix = name[len(entity) + 1 :]
        if suffix == "classes.json":
            return True
        from app.training.algorithms import ALGORITHMS

        if any(suffix in algorithm.suffixes for algorithm in ALGORITHMS.values()):
            return True
    return False
