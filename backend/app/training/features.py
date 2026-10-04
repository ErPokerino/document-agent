"""From a document to a row of numbers: its text, and optionally fields extracted from it.

Text becomes TF-IDF, optionally reduced by truncated SVD — linear models read
the sparse vector well, trees prefer a few hundred dense components. Fields
become columns of their own: a number as itself, a date as its year, month
and day, anything else as one indicator per value seen in training (rare
values pooled, an unseen one all zeros).

Everything fitted is stored as JSON or NumPy arrays and rebuilt on load, for
the same reason as the nearest-neighbour model: a pickle runs code when read.
"""

import io
import json
from typing import Any

import numpy as np
import scipy.sparse as sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from app.domain.models import EntityDefinition, EntityFormat, TextFeatures, category_key
from app.evaluation.scoring import _normalize_date

# A value met fewer times than this in training is not given a column.
MIN_VALUE_COUNT = 2
MAX_VALUES_PER_FIELD = 200


def _vectorizer(spec: TextFeatures) -> TfidfVectorizer:
    return TfidfVectorizer(
        analyzer=spec.analyzer,
        ngram_range=(spec.ngram_min, spec.ngram_max),
        lowercase=True,
        strip_accents="unicode",
        sublinear_tf=spec.sublinear_tf,
        min_df=spec.min_df,
        max_df=spec.max_df,
        max_features=spec.max_features,
        norm="l2",
        dtype=np.float32,
    )


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


class Featurizer:
    def __init__(self, spec: TextFeatures, fields: list[EntityDefinition]) -> None:
        self.spec = spec
        self.fields = fields
        self.vectorizer: TfidfVectorizer | None = None
        self.components: np.ndarray | None = None
        # For each categorical field, the values that have a column.
        self.values: dict[str, list[str]] = {}

    # -- fitting ---------------------------------------------------------------

    def fit_transform(self, texts: list[str], rows: list[dict[str, Any]]) -> Any:
        self.vectorizer = _vectorizer(self.spec)
        try:
            tfidf = self.vectorizer.fit_transform([text[: self.spec.max_characters] for text in texts])
        except ValueError as exc:
            raise ValueError(f"The text could not be turned into features: {exc}") from exc
        if self.spec.reduce_to:
            # Never more components than the data has room for.
            dimensions = max(1, min(self.spec.reduce_to, tfidf.shape[0] - 1, tfidf.shape[1] - 1))
            svd = TruncatedSVD(n_components=dimensions, random_state=0)
            svd.fit(tfidf)
            self.components = svd.components_.astype(np.float32)
        for entity in self.fields:
            if self._kind(entity) != "categorical":
                continue
            counts: dict[str, int] = {}
            for row in rows:
                value = row.get(entity.name)
                if value is not None:
                    counts[category_key(value)] = counts.get(category_key(value), 0) + 1
            kept = sorted((key for key, count in counts.items() if count >= MIN_VALUE_COUNT), key=lambda key: (-counts[key], key))
            self.values[entity.name] = kept[:MAX_VALUES_PER_FIELD]
        return self._combine(tfidf, rows)

    def transform(self, texts: list[str], rows: list[dict[str, Any]]) -> Any:
        assert self.vectorizer is not None
        tfidf = self.vectorizer.transform([text[: self.spec.max_characters] for text in texts])
        return self._combine(tfidf, rows)

    # -- columns ---------------------------------------------------------------

    @staticmethod
    def _kind(entity: EntityDefinition) -> str:
        if entity.format in (EntityFormat.decimal, EntityFormat.integer):
            return "numeric"
        if entity.format is EntityFormat.date:
            return "date"
        return "categorical"

    def _field_columns(self, rows: list[dict[str, Any]]) -> np.ndarray | None:
        blocks = []
        for entity in self.fields:
            kind = self._kind(entity)
            if kind == "numeric":
                blocks.append(np.array([[_number(row.get(entity.name))] for row in rows], dtype=np.float32))
            elif kind == "date":
                parts = []
                for row in rows:
                    normalized = _normalize_date(row.get(entity.name))
                    parts.append([float(piece) for piece in normalized.split("-")] if normalized else [np.nan] * 3)
                blocks.append(np.array(parts, dtype=np.float32))
            else:
                values = self.values.get(entity.name, [])
                block = np.zeros((len(rows), len(values) + 1), dtype=np.float32)
                for index, row in enumerate(rows):
                    value = row.get(entity.name)
                    if value is None:
                        continue
                    key = category_key(value)
                    # The last column is "a value with no column of its own".
                    block[index, values.index(key) if key in values else len(values)] = 1.0
                blocks.append(block)
        return np.hstack(blocks) if blocks else None

    def _combine(self, tfidf: Any, rows: list[dict[str, Any]]) -> Any:
        text = tfidf @ self.components.T if self.components is not None else tfidf
        fields = self._field_columns(rows)
        if fields is None:
            return text
        if sparse.issparse(text):
            # Missing numbers are zero in a sparse matrix; trees read NaN, but
            # a sparse block cannot carry it.
            return sparse.hstack([text, sparse.csr_matrix(np.nan_to_num(fields))]).tocsr()
        return np.hstack([np.asarray(text, dtype=np.float32), fields])

    # -- storage ---------------------------------------------------------------

    def files(self) -> dict[str, bytes]:
        assert self.vectorizer is not None
        idf = io.BytesIO()
        np.save(idf, self.vectorizer.idf_.astype(np.float64), allow_pickle=False)
        vocabulary = {term: int(index) for term, index in sorted(self.vectorizer.vocabulary_.items(), key=lambda pair: pair[1])}
        stored = {
            "vocabulary.json": json.dumps(vocabulary, ensure_ascii=False).encode("utf-8"),
            "idf.npy": idf.getvalue(),
            "fields.json": json.dumps(
                {"fields": [entity.model_dump(mode="json") for entity in self.fields], "values": self.values},
                ensure_ascii=False,
            ).encode("utf-8"),
        }
        if self.components is not None:
            components = io.BytesIO()
            np.save(components, self.components, allow_pickle=False)
            stored["svd.npy"] = components.getvalue()
        return stored

    @classmethod
    def from_files(cls, files: dict[str, bytes], spec: TextFeatures) -> "Featurizer":
        described = json.loads(files["fields.json"].decode("utf-8"))
        featurizer = cls(spec, [EntityDefinition.model_validate(entity) for entity in described["fields"]])
        featurizer.values = {name: list(values) for name, values in described["values"].items()}
        vocabulary = json.loads(files["vocabulary.json"].decode("utf-8"))
        idf = np.load(io.BytesIO(files["idf.npy"]), allow_pickle=False)
        if len(vocabulary) != idf.shape[0]:
            raise ValueError("The stored vocabulary and weights do not fit together")
        featurizer.vectorizer = _vectorizer(spec)
        featurizer.vectorizer.vocabulary_ = vocabulary
        featurizer.vectorizer.idf_ = idf
        if "svd.npy" in files:
            featurizer.components = np.load(io.BytesIO(files["svd.npy"]), allow_pickle=False)
        return featurizer
