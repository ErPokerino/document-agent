"""Nearest neighbour over TF-IDF: a document's classes are those of the most similar one.

Invoices from one supplier share a layout, a vocabulary and usually the same
cost centre, document type and supplier id. Embedding the text of every
labelled document as a TF-IDF vector and taking the categorical labels of the
closest one predicts those fields without a model call, and the similarity is a
number to set a threshold on — which a model's stated confidence is not.

What is stored is declarative: the vocabulary as JSON, the IDF weights and the
document matrix as NumPy arrays read with `allow_pickle=False`, and the labels
as JSON. A pickled estimator would execute whatever code it carried when
loaded, so an artefact brought from another machine could not be trusted.

Rebuilding the vectorizer from that vocabulary and those weights reproduces
`transform` exactly for the scikit-learn version pinned in the lock file; the
version that trained an artefact is recorded in its manifest.
"""

import io
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import scipy.sparse as sparse
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer

from app.domain.models import KnnParameters, category_key

KIND = "knn_tfidf"
FILES = ("vocabulary.json", "idf.npy", "matrix.npz", "documents.json")



@dataclass(frozen=True)
class TrainingDocument:
    dataset: str
    document: str
    sha256: str
    labels: dict[str, Any]


@dataclass(frozen=True)
class Neighbour:
    index: int
    similarity: float


@dataclass(frozen=True)
class Prediction:
    value: Any
    # The similarity of the nearest document that voted for the value. What a
    # threshold is set on.
    score: float
    # The share of the vote the value won, from 0 to 1.
    agreement: float
    nearest: TrainingDocument | None


class KnnModel:
    def __init__(
        self,
        vectorizer: TfidfVectorizer,
        matrix: sparse.csr_matrix,
        documents: list[TrainingDocument],
        parameters: KnnParameters,
    ) -> None:
        self.vectorizer = vectorizer
        self.matrix = matrix
        self.documents = documents
        self.parameters = parameters
        self.votes = parameters.k

    # -- training ------------------------------------------------------------

    @classmethod
    def train(cls, texts: list[str], documents: list[TrainingDocument], parameters: KnnParameters) -> "KnnModel":
        if len(texts) != len(documents):
            raise ValueError("Every training document needs its text")
        if len(texts) < 2:
            raise ValueError("At least two labelled documents with text are needed to train")
        vectorizer = _vectorizer(parameters)
        try:
            matrix = vectorizer.fit_transform([text[: parameters.max_characters] for text in texts])
        except ValueError as exc:
            # scikit-learn's own words, e.g. "max_df corresponds to < documents than min_df".
            raise ValueError(f"The text could not be turned into features: {exc}") from exc
        return cls(vectorizer, sparse.csr_matrix(matrix, dtype=np.float32), documents, parameters)

    # -- prediction ------------------------------------------------------------

    def similarities(self, text: str) -> np.ndarray:
        vector = self.vectorizer.transform([text[: self.parameters.max_characters]])
        # Rows are L2-normalized, so the dot product is the cosine similarity.
        return np.asarray((self.matrix @ vector.T).todense()).ravel()

    def predict(self, text: str, entity: str, *, exclude: set[int] | None = None) -> Prediction | None:
        return self._vote(self.similarities(text), entity, exclude or set())

    def predict_all(self, text: str, entities: list[str], fields: dict[str, Any] | None = None) -> dict[str, Prediction | None]:
        """Every field from one comparison: the similarities do not depend on the field.

        `fields` is accepted and ignored: a neighbour is found from text alone.
        """
        similarities = self.similarities(text)
        return {entity: self._vote(similarities, entity, set()) for entity in entities}

    def _vote(self, similarities: np.ndarray, entity: str, exclude: set[int]) -> Prediction | None:
        # Only documents labelled for this field vote. One labelled "absent"
        # votes for no value, which is an answer; one never labelled for it
        # has nothing to say.
        order = np.argsort(-similarities, kind="stable")
        voters: list[Neighbour] = []
        for index in order:
            index = int(index)
            if index in exclude or entity not in self.documents[index].labels:
                continue
            voters.append(Neighbour(index, float(similarities[index])))
            if len(voters) == self.parameters.k:
                break
        if not voters:
            return None

        weights: dict[str, float] = {}
        first: dict[str, Neighbour] = {}
        values: dict[str, Any] = {}
        for voter in voters:
            value = self.documents[voter.index].labels[entity]
            key = "\u0000none" if value is None else category_key(value)
            weight = max(voter.similarity, 0.0) if self.parameters.weighting == "distance" else 1.0
            weights[key] = weights.get(key, 0.0) + weight
            first.setdefault(key, voter)
            values.setdefault(key, value)
        total = sum(weights.values())
        # Ties go to the class whose nearest voter is closer.
        winner = max(weights, key=lambda key: (weights[key], first[key].similarity))
        nearest = first[winner]
        return Prediction(
            value=values[winner],
            score=round(nearest.similarity, 4),
            agreement=round(weights[winner] / total, 4) if total else 1.0,
            nearest=self.documents[nearest.index],
        )

    # -- validation ------------------------------------------------------------

    def leave_one_out(self, entity: str) -> list[tuple[Any, Prediction | None]]:
        """Each labelled document predicted from all the others.

        A copy of the same file in a second dataset is left out with it: it
        would otherwise be its own nearest neighbour under another name.
        """
        similarities = (self.matrix @ self.matrix.T).toarray()
        by_hash: dict[str, list[int]] = {}
        for index, document in enumerate(self.documents):
            by_hash.setdefault(document.sha256, []).append(index)
        outcomes = []
        for index, document in enumerate(self.documents):
            if entity not in document.labels:
                continue
            exclude = set(by_hash[document.sha256])
            outcomes.append((document.labels[entity], self._vote(similarities[index], entity, exclude)))
        return outcomes

    # -- storage ---------------------------------------------------------------

    def files(self) -> dict[str, bytes]:
        idf = io.BytesIO()
        np.save(idf, self.vectorizer.idf_.astype(np.float64), allow_pickle=False)
        matrix = io.BytesIO()
        sparse.save_npz(matrix, self.matrix, compressed=True)
        vocabulary = {term: int(index) for term, index in sorted(self.vectorizer.vocabulary_.items(), key=lambda pair: pair[1])}
        return {
            "vocabulary.json": json.dumps(vocabulary, ensure_ascii=False).encode("utf-8"),
            "idf.npy": idf.getvalue(),
            "matrix.npz": matrix.getvalue(),
            "documents.json": json.dumps(
                [
                    {"dataset": d.dataset, "document": d.document, "sha256": d.sha256, "labels": d.labels}
                    for d in self.documents
                ],
                ensure_ascii=False,
            ).encode("utf-8"),
        }

    @classmethod
    def from_files(cls, files: dict[str, bytes], parameters: KnnParameters) -> "KnnModel":
        vocabulary = json.loads(files["vocabulary.json"].decode("utf-8"))
        idf = np.load(io.BytesIO(files["idf.npy"]), allow_pickle=False)
        matrix = sparse.load_npz(io.BytesIO(files["matrix.npz"])).tocsr().astype(np.float32)
        documents = [
            TrainingDocument(
                dataset=str(entry["dataset"]),
                document=str(entry["document"]),
                sha256=str(entry["sha256"]),
                labels=dict(entry["labels"]),
            )
            for entry in json.loads(files["documents.json"].decode("utf-8"))
        ]
        if len(vocabulary) != idf.shape[0] or matrix.shape != (len(documents), idf.shape[0]):
            raise ValueError("The stored vocabulary, weights and documents do not fit together")
        vectorizer = _vectorizer(parameters)
        vectorizer.vocabulary_ = vocabulary
        vectorizer.idf_ = idf
        return cls(vectorizer, matrix, documents, parameters)


def _vectorizer(parameters: KnnParameters) -> TfidfVectorizer:
    return TfidfVectorizer(
        analyzer=parameters.analyzer,
        ngram_range=(parameters.ngram_min, parameters.ngram_max),
        lowercase=True,
        strip_accents="unicode",
        sublinear_tf=parameters.sublinear_tf,
        min_df=parameters.min_df,
        max_df=parameters.max_df,
        max_features=parameters.max_features,
        norm="l2",
        dtype=np.float32,
    )


def library_versions() -> dict[str, str]:
    return {"scikit-learn": sklearn.__version__, "numpy": np.__version__, "scipy": __import__("scipy").__version__}
