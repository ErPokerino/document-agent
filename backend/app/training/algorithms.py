"""The algorithms a model can be trained with, each described well enough to be drawn and checked.

Adding one is a class here: what it is called, its family, the package it
needs, its parameters with their bounds, and how it fits, predicts, saves and
loads. Nothing in the UI names an algorithm, so a new one appears in Models
without a line of frontend code.

Every algorithm saves to a format that is data, never a pickle: weights as
NumPy arrays, LightGBM's text model, XGBoost's JSON, CatBoost's own binary
format. Loading a model from another machine then cannot run code.

An algorithm whose package is not installed is listed as such, with the
command that installs it; one that runs on a service DocuFlow does not reach is
listed as not connected. Neither can be trained, and neither is pretended.
"""

import importlib.util
import io
import os
import tempfile
from typing import Any

import numpy as np

from app.domain.models import AlgorithmInfo, ParameterSpec

CLASS_WEIGHT = ParameterSpec(
    name="class_weight", label="Class weights", kind="choice", default="none", choices=["none", "balanced"],
    help="Balanced weighs each class by the inverse of how often it occurs, so a rare class is not ignored.",
)


def _dense(matrix: Any) -> Any:
    return matrix.toarray() if hasattr(matrix, "toarray") else matrix


def _two_columns(probabilities: np.ndarray) -> np.ndarray:
    """A binary model's one column as the two the rest of the code reads."""
    if probabilities.ndim == 1:
        return np.column_stack([1 - probabilities, probabilities])
    return probabilities


class Algorithm:
    id = ""
    label = ""
    family = "linear"
    description = ""
    package: str | None = None
    install: str | None = None
    runs = "local"
    reads_text = True
    takes_fields = True
    default_reduce_to: int | None = None
    parameters: list[ParameterSpec] = []
    suffixes: tuple[str, ...] = ()

    def status(self) -> str:
        if self.runs == "remote":
            return "not_connected"
        if self.package and importlib.util.find_spec(self.package) is None:
            return "not_installed"
        return "available"

    def info(self) -> AlgorithmInfo:
        return AlgorithmInfo(
            id=self.id, label=self.label, family=self.family, description=self.description,  # type: ignore[arg-type]
            status=self.status(), runs=self.runs, install=self.install,  # type: ignore[arg-type]
            reads_text=self.reads_text, takes_fields=self.takes_fields,
            default_reduce_to=self.default_reduce_to, parameters=self.parameters,
        )

    def resolve(self, given: dict[str, Any]) -> dict[str, Any]:
        """The parameters to train with: defaults filled in, each one checked."""
        known = {spec.name: spec for spec in self.parameters}
        unknown = sorted(set(given) - set(known))
        if unknown:
            raise ValueError(f"{self.label} has no parameter named {', '.join(unknown)}")
        resolved: dict[str, Any] = {}
        for name, spec in known.items():
            value = given.get(name, spec.default)
            if spec.kind == "int":
                value = int(value)
            elif spec.kind == "float":
                value = float(value)
            elif spec.kind == "bool":
                value = bool(value)
            elif spec.kind == "choice" and value not in spec.choices:
                raise ValueError(f"{spec.label} must be one of: {', '.join(spec.choices)}")
            if spec.minimum is not None and value < spec.minimum or spec.maximum is not None and value > spec.maximum:
                raise ValueError(f"{spec.label} must be between {spec.minimum:g} and {spec.maximum:g}")
            resolved[name] = value
        return resolved

    # Implemented by each trainable algorithm.
    def fit(self, features: Any, labels: np.ndarray, classes: int, parameters: dict[str, Any]) -> Any:
        raise NotImplementedError

    def predict(self, model: Any, features: Any) -> np.ndarray:
        raise NotImplementedError

    def save(self, model: Any, prefix: str) -> dict[str, bytes]:
        raise NotImplementedError

    def load(self, files: dict[str, bytes], prefix: str, parameters: dict[str, Any]) -> Any:
        raise NotImplementedError


class NearestNeighbour(Algorithm):
    id = "knn_tfidf"
    label = "Nearest neighbour"
    family = "neighbours"
    description = (
        "A document takes the labels of the most similar labelled document, or the "
        "similarity-weighted vote of the k nearest. Nothing is fitted beyond the "
        "vocabulary, so it learns from a handful of examples per class, and every "
        "answer names the document it came from."
    )
    package = "sklearn"
    takes_fields = False
    parameters = [
        ParameterSpec(name="k", label="Neighbours (k)", kind="int", default=1, minimum=1, maximum=25, step=1,
                      help="How many of the nearest labelled documents vote. 1 takes the single nearest."),
        ParameterSpec(name="weighting", label="Votes weighted by", kind="choice", default="distance", choices=["distance", "uniform"],
                      help="Distance weighs each vote by similarity; uniform gives each one vote."),
    ]


class LogisticRegression(Algorithm):
    id = "logistic_regression"
    label = "Logistic regression"
    family = "linear"
    description = (
        "One weight per feature and class, fitted to the labels. Reads the sparse TF-IDF "
        "directly, trains in seconds, and gives a probability per class rather than a "
        "similarity."
    )
    package = "sklearn"
    parameters = [
        ParameterSpec(name="C", label="Inverse regularization (C)", kind="float", default=1.0, minimum=0.0001, maximum=10000, step=0.1,
                      help="Smaller values keep the weights small, which generalizes better from few documents; larger values fit the training documents more closely."),
        CLASS_WEIGHT,
        ParameterSpec(name="max_iter", label="Iterations", kind="int", default=1000, minimum=50, maximum=10000, step=50,
                      help="The most iterations the solver may take to converge."),
    ]
    suffixes = ("coef.npy", "intercept.npy")

    def fit(self, features, labels, classes, parameters):
        from sklearn.linear_model import LogisticRegression as Estimator

        model = Estimator(
            C=parameters["C"], max_iter=parameters["max_iter"],
            class_weight="balanced" if parameters["class_weight"] == "balanced" else None,
        )
        model.fit(features, labels)
        return {"coef": model.coef_.astype(np.float64), "intercept": model.intercept_.astype(np.float64)}

    def predict(self, model, features):
        scores = np.asarray(features @ model["coef"].T) + model["intercept"]
        if model["coef"].shape[0] == 1:
            return _two_columns(1 / (1 + np.exp(-scores[:, 0])))
        scores -= scores.max(axis=1, keepdims=True)
        exponentials = np.exp(scores)
        return exponentials / exponentials.sum(axis=1, keepdims=True)

    def save(self, model, prefix):
        stored = {}
        for key in ("coef", "intercept"):
            buffer = io.BytesIO()
            np.save(buffer, model[key], allow_pickle=False)
            stored[f"{prefix}.{key}.npy"] = buffer.getvalue()
        return stored

    def load(self, files, prefix, parameters):
        return {key: np.load(io.BytesIO(files[f"{prefix}.{key}.npy"]), allow_pickle=False) for key in ("coef", "intercept")}


class LightGbm(Algorithm):
    id = "lightgbm"
    label = "LightGBM"
    family = "boosting"
    description = (
        "Gradient-boosted trees grown leaf by leaf. Fast on many rows and columns; on a "
        "few dozen documents trees have little to split, so keep leaves small."
    )
    package = "lightgbm"
    install = "pip install lightgbm"
    default_reduce_to = 256
    parameters = [
        ParameterSpec(name="n_estimators", label="Trees", kind="int", default=200, minimum=10, maximum=5000, step=10),
        ParameterSpec(name="learning_rate", label="Learning rate", kind="float", default=0.1, minimum=0.001, maximum=1, step=0.01),
        ParameterSpec(name="num_leaves", label="Leaves per tree", kind="int", default=15, minimum=2, maximum=512, step=1),
        ParameterSpec(name="min_child_samples", label="Documents per leaf", kind="int", default=2, minimum=1, maximum=200, step=1,
                      help="LightGBM's own default is 20, which on a small dataset leaves no split to make."),
        CLASS_WEIGHT,
    ]
    suffixes = ("lgbm.txt",)

    def fit(self, features, labels, classes, parameters):
        import lightgbm

        model = lightgbm.LGBMClassifier(
            n_estimators=parameters["n_estimators"], learning_rate=parameters["learning_rate"],
            num_leaves=parameters["num_leaves"], min_child_samples=parameters["min_child_samples"],
            class_weight="balanced" if parameters["class_weight"] == "balanced" else None,
            random_state=0, verbose=-1,
        )
        model.fit(features, labels)
        return model.booster_.model_to_string()

    def predict(self, model, features):
        import lightgbm

        booster = model if isinstance(model, lightgbm.Booster) else lightgbm.Booster(model_str=model)
        return _two_columns(np.asarray(booster.predict(features)))

    def save(self, model, prefix):
        return {f"{prefix}.lgbm.txt": model.encode("utf-8")}

    def load(self, files, prefix, parameters):
        import lightgbm

        return lightgbm.Booster(model_str=files[f"{prefix}.lgbm.txt"].decode("utf-8"))


class XgBoost(Algorithm):
    id = "xgboost"
    label = "XGBoost"
    family = "boosting"
    description = "Gradient-boosted trees grown level by level, with histogram splits."
    package = "xgboost"
    install = "pip install xgboost"
    default_reduce_to = 256
    parameters = [
        ParameterSpec(name="n_estimators", label="Trees", kind="int", default=200, minimum=10, maximum=5000, step=10),
        ParameterSpec(name="max_depth", label="Depth", kind="int", default=4, minimum=1, maximum=16, step=1),
        ParameterSpec(name="learning_rate", label="Learning rate", kind="float", default=0.1, minimum=0.001, maximum=1, step=0.01),
        ParameterSpec(name="subsample", label="Share of documents per tree", kind="float", default=1.0, minimum=0.1, maximum=1, step=0.05),
    ]
    suffixes = ("xgb.json",)

    def fit(self, features, labels, classes, parameters):
        import xgboost

        model = xgboost.XGBClassifier(
            n_estimators=parameters["n_estimators"], max_depth=parameters["max_depth"],
            learning_rate=parameters["learning_rate"], subsample=parameters["subsample"],
            tree_method="hist", random_state=0, n_jobs=os.cpu_count() or 1,
        )
        model.fit(features, labels)
        return bytes(model.get_booster().save_raw(raw_format="json"))

    def predict(self, model, features):
        import xgboost

        booster = model if isinstance(model, xgboost.Booster) else self.load({"m.xgb.json": model}, "m", {})
        return _two_columns(np.asarray(booster.predict(xgboost.DMatrix(features))))

    def save(self, model, prefix):
        return {f"{prefix}.xgb.json": model}

    def load(self, files, prefix, parameters):
        import xgboost

        booster = xgboost.Booster()
        booster.load_model(bytearray(files[f"{prefix}.xgb.json"]))
        return booster


class CatBoost(Algorithm):
    id = "catboost"
    label = "CatBoost"
    family = "boosting"
    description = "Gradient-boosted symmetric trees with ordered boosting, steady with default settings."
    package = "catboost"
    install = "pip install catboost"
    default_reduce_to = 256
    parameters = [
        ParameterSpec(name="iterations", label="Trees", kind="int", default=300, minimum=10, maximum=5000, step=10),
        ParameterSpec(name="depth", label="Depth", kind="int", default=6, minimum=1, maximum=10, step=1),
        ParameterSpec(name="learning_rate", label="Learning rate", kind="float", default=0.1, minimum=0.001, maximum=1, step=0.01),
        ParameterSpec(name="l2_leaf_reg", label="L2 regularization", kind="float", default=3.0, minimum=0.0, maximum=100, step=0.5),
    ]
    suffixes = ("cbm",)

    def fit(self, features, labels, classes, parameters):
        import catboost

        model = catboost.CatBoostClassifier(
            iterations=parameters["iterations"], depth=parameters["depth"],
            learning_rate=parameters["learning_rate"], l2_leaf_reg=parameters["l2_leaf_reg"],
            random_seed=0, verbose=False, allow_writing_files=False,
        )
        model.fit(_dense(features), labels)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "model.cbm")
            model.save_model(path, format="cbm")
            with open(path, "rb") as stored:
                return stored.read()

    def predict(self, model, features):
        import catboost

        loaded = model if isinstance(model, catboost.CatBoostClassifier) else self.load({"m.cbm": model}, "m", {})
        return _two_columns(np.asarray(loaded.predict_proba(_dense(features))))

    def save(self, model, prefix):
        return {f"{prefix}.cbm": model}

    def load(self, files, prefix, parameters):
        import catboost

        return catboost.CatBoostClassifier().load_model(blob=files[f"{prefix}.cbm"])


class TabPfn(Algorithm):
    id = "tabpfn"
    label = "TabPFN"
    family = "foundation"
    description = (
        "A tabular foundation model: a transformer pre-trained on synthetic tables that "
        "predicts by reading the training rows in context, with no fitting of its own. "
        "Suited to small tables of up to a few hundred features, so the text is reduced first."
    )
    package = "tabpfn"
    install = "pip install tabpfn (brings PyTorch; the model weights are downloaded on first use)"
    default_reduce_to = 100
    parameters = [
        ParameterSpec(name="n_estimators", label="Ensemble members", kind="int", default=4, minimum=1, maximum=32, step=1,
                      help="How many differently preprocessed copies of the table the model reads and averages."),
    ]
    suffixes = ("rows.npy", "labels.npy")

    # In-context: the "model" is the training rows themselves, stored as arrays.
    def fit(self, features, labels, classes, parameters):
        return {
            "rows": np.asarray(_dense(features), dtype=np.float32),
            "labels": np.asarray(labels),
            "n_estimators": parameters["n_estimators"],
        }

    def predict(self, model, features):
        from tabpfn import TabPFNClassifier

        estimator = TabPFNClassifier(n_estimators=model.get("n_estimators", 4))
        estimator.fit(model["rows"], model["labels"])
        return _two_columns(np.asarray(estimator.predict_proba(np.asarray(_dense(features), dtype=np.float32))))

    def save(self, model, prefix):
        stored = {}
        for key in ("rows", "labels"):
            buffer = io.BytesIO()
            np.save(buffer, model[key], allow_pickle=False)
            stored[f"{prefix}.{key}.npy"] = buffer.getvalue()
        return stored

    def load(self, files, prefix, parameters):
        return {
            **{key: np.load(io.BytesIO(files[f"{prefix}.{key}.npy"]), allow_pickle=False) for key in ("rows", "labels")},
            "n_estimators": parameters.get("n_estimators", 4),
        }


class Jev(Algorithm):
    id = "jev"
    label = "Jev"
    family = "foundation"
    description = (
        "TypeSafe AI's hosted decision model, in limited early access since September 2026: "
        "given text and a typed question, it returns one of the predefined answers with "
        "probabilities. It would answer a categorical field without training here."
    )
    runs = "remote"
    takes_fields = False


ALGORITHMS: dict[str, Algorithm] = {
    algorithm.id: algorithm
    for algorithm in (NearestNeighbour(), LogisticRegression(), LightGbm(), XgBoost(), CatBoost(), TabPfn(), Jev())
}


def algorithm(identity: str) -> Algorithm:
    found = ALGORITHMS.get(identity)
    if found is None:
        raise ValueError(f"{identity!r} is not an algorithm this version knows")
    return found
